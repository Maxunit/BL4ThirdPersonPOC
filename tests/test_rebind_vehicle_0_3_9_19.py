"""Integration ownership, first-start, cancellation and pre-copy protection tests.

SDK/native APIs are substituted; Windows/game animation QA remains external.
"""
import ast
import ctypes
import hashlib
from pathlib import Path
import struct
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace as S
import support
from BL4ThirdPersonPOC.omni import rebind_cache as cachemod
from BL4ThirdPersonPOC.omni.rebind_cache import RebindCache, BoundLayout, ClassEntry
from BL4ThirdPersonPOC.omni.vehicle_handoff import VehicleHandoff, ExitAir, allow_exit_air
from BL4ThirdPersonPOC.omni.vehicle_exit import ExitFacing
from BL4ThirdPersonPOC.omni.vehicle_summon import SummonFacing
from BL4ThirdPersonPOC.omni.session import GameplaySession
from BL4ThirdPersonPOC.native_memory import _native_write_code
from BL4ThirdPersonPOC import hybrid_ads

BASE = 0x140000000

class Info(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
        ('AllocationProtect', ctypes.c_uint32), ('PartitionId', ctypes.c_uint16),
        ('RegionSize', ctypes.c_size_t), ('State', ctypes.c_uint32), ('Protect', ctypes.c_uint32), ('Type', ctypes.c_uint32)]

def obj(name, address, **kw):
    return S(Class=S(Name=name), _get_address=lambda: address, **kw)

class RebindTests(unittest.TestCase):
    def setUp(self):
        self.updates = S(is_game_thread=lambda: True)
        self.mod = S(_MEMORY_BASIC_INFORMATION=Info)
        self.sup = S(active=True, mod=self.mod, updates=self.updates)
        self.capture = S(active=True, mod=self.mod, updates=self.updates, lifecycle_supervisor=self.sup)
        self.sup.child = self.capture
        self.mod._player_omnidirectional_gameplay = self.sup
        self.cache = RebindCache(self.sup)
        self.calls = []
        self.protect = 0x20
        self.cache.page_size = 4096

    def fresh(self, address):
        self.calls.append(address)
        return Info(BASE+0x153000, BASE, 0x80, 0, 0x9000000, 0x1000, self.protect, 0x1000000)

    def test_only_one_callback_and_fresh_first_query_then_seed(self):
        rv = sorted(cachemod.REGION_RVAS)
        for iteration in range(2):
            with self.cache.transaction(self.capture):
                infos = [self.cache.query_region(BASE+r, self.fresh) for r in rv]
                self.assertEqual(len(self.calls), 2*(iteration+1))
                self.assertIsNot(infos[1], infos[2])
                self.assertEqual(len(self.cache.region['pending']), 9)
            self.assertIsNone(self.cache.region)
            self.assertFalse(hasattr(self.mod, '_omni_rebind_memory'))
        self.assertEqual(self.cache.totals['reused_queries'], 18)

    def test_seed_error_falls_back_to_original_queries(self):
        n = 0
        def fresh(address):
            nonlocal n
            n += 1
            if n == 2: raise RuntimeError('unavailable')
            return self.fresh(address)
        with self.cache.transaction(self.capture):
            for r in sorted(cachemod.REGION_RVAS): self.cache.query_region(BASE+r, fresh)
        self.assertEqual(n, 11)
        self.assertEqual(self.cache.totals['reused_queries'], 0)

    def test_cross_page_unknown_and_foreign_thread_query_are_fresh(self):
        with self.cache.transaction(self.capture):
            self.cache.query_region(BASE+min(cachemod.REGION_RVAS), self.fresh)
            self.cache.query_region(BASE+0x153fff, self.fresh)
            self.cache.query_region(BASE+0x123456, self.fresh)
            with patch.object(self.cache, 'thread', -1):
                self.cache.query_region(BASE+0x120a80a, self.fresh)
        self.assertEqual(len(self.calls), 5)

    def writer(self, admission, *, failure=None):
        events = []
        def protect(address, size, desired, out):
            events.append(('protect', desired))
            ctypes.cast(out, ctypes.POINTER(ctypes.c_ulong)).contents.value = self.protect
            return 1
        api = S(VirtualProtect=protect, GetCurrentProcess=lambda: -1,
                FlushInstructionCache=lambda *a: events.append(('flush',)) or 1)
        def copy(*args):
            events.append(('copy',))
            if failure is not None: raise failure
        with patch.object(ctypes, 'memmove', side_effect=copy):
            _native_write_code(BASE+0x120a80a, b'x'*20, _kernel32=api,
                               _PAGE_EXECUTE_READWRITE=0x40, _admit=admission)
        return events

    def prime(self):
        self.cache.query_region(BASE+0x153950, self.fresh)
        self.cache.query_region(BASE+0x120a80a, self.fresh)
        return self.cache.write_admission(BASE+0x120a80a, b'x'*20)

    def test_protection_admission_precedes_copy_and_ticket_consumed(self):
        with self.cache.transaction(self.capture):
            admission = self.prime()
            events = self.writer(admission)
            self.assertEqual(events, [('protect',0x40),('copy',),('flush',),('protect',0x20)])
            self.assertNotIn(BASE+0x120a80a, self.cache.region['pending'])

    def test_mismatch_restores_actual_protection_without_copy(self):
        with self.cache.transaction(self.capture):
            admission = self.prime()
            self.protect = 0x80
            calls = []
            def protect(address, size, desired, out):
                calls.append(desired)
                ctypes.cast(out, ctypes.POINTER(ctypes.c_ulong)).contents.value = 0x80
                return 1
            api = S(VirtualProtect=protect)
            with patch.object(ctypes, 'memmove') as copy:
                with self.assertRaisesRegex(RuntimeError, 'protection changed'):
                    _native_write_code(BASE+0x120a80a,b'x'*20,_kernel32=api,
                        _PAGE_EXECUTE_READWRITE=0x40,_admit=admission)
                copy.assert_not_called()
            self.assertEqual(calls, [0x40,0x80])

    def test_copy_failure_does_not_leave_stale_ticket_blocking_cleanup(self):
        with self.cache.transaction(self.capture):
            admission = self.prime()
            exc = ValueError('copy failed')
            with self.assertRaises(ValueError) as caught: self.writer(admission, failure=exc)
            self.assertIs(caught.exception, exc)
            self.assertIsNone(self.cache.write_admission(BASE+0x120a80a, b'x'*20))

    def test_changed_owner_and_oversized_write_refused_before_protection(self):
        with self.cache.transaction(self.capture):
            self.prime()
            with self.assertRaisesRegex(RuntimeError, 'owner/page'):
                self.cache.write_admission(BASE+0x120a80a, b'x'*65)
            self.capture.active = False
            with self.assertRaisesRegex(RuntimeError, 'owner/page'):
                self.cache.write_admission(BASE+0x120a80a, b'x'*20)

    def test_exception_clears_context_bones_and_class_entry(self):
        self.cache.entry = self.cache.bones = object()
        with self.assertRaises(ValueError):
            with self.cache.transaction(self.capture): raise ValueError('original')
        self.assertIsNone(self.cache.entry)
        self.assertIsNone(self.cache.bones)
        self.assertFalse(hasattr(self.mod, '_omni_rebind_memory'))

    def test_original_ground_pipeline_with_real_session_flags(self):
        c = GameplaySession.__new__(GameplaySession)
        c.active, c.busy, c.lifecycle_supervisor = True, False, self.sup
        c.mod, c.updates = self.mod, self.updates
        for name in ('ready','blend_layout_ready','player_ready','sprint_ready','route_ready','vector_ready','entry_ready'):
            setattr(c, name, False)
        self.sup.child = c
        self.sup.rebind_cache = self.cache
        seen = []
        c._input_source_frame = lambda *args: seen.append(('input',self.cache.owned()))
        c.observe_ground_input_pose = lambda stage: seen.append((stage,self.cache.owned()))
        c._ground_pose_frame(None,None,None,None)
        self.assertEqual(seen, [('input',True),('POST',True)])
        self.assertIsNone(self.cache.capture)

    def animation_fixture(self):
        props = [obj('NameProperty',0x24000000,Name='Aim',Offset_Internal=32),
                 obj('NameProperty',0x24000100,Name='Other',Offset_Internal=64),
                 obj('NameProperty',0x24000200,Name='Aim',Offset_Internal=96)]
        schema = obj('Class',0x25000000,_superfields=lambda:(),_properties=lambda:props)
        anim = obj('Anim',0x26000000)
        anim.Class=schema
        mesh = obj('Mesh',0x27000000,AnimScriptInstance=anim)
        pawn = obj('OakCharacter',0x28000000,Mesh=mesh)
        self.capture.bound=lambda:(None,pawn,None,None)
        self.capture.mesh_ref=lambda:mesh;self.capture.anim_ref=lambda:anim
        self.capture.anim_address=anim._get_address()
        return anim,schema,props

    def test_class_reuse_scans_fresh_ordered_properties_and_preserves_duplicates(self):
        anim,schema,props=self.animation_fixture()
        for turn in range(2):
            with self.cache.transaction(self.capture):
                owners=self.cache.query_layout('owners',self.capture,anim)
                selected=self.cache.query_layout('props',self.capture,anim,owners[0],('names',('Aim',)))
                self.assertEqual([p.Offset_Internal for p in selected],[32,96])
        self.assertEqual(self.cache.totals['class_hits'],1)
        self.assertEqual(self.cache.stats['property_scans'],2)
        props.reverse()
        with self.cache.transaction(self.capture):
            owners=self.cache.query_layout('owners',self.capture,anim)
            selected=self.cache.query_layout('props',self.capture,anim,owners[0],('names',('Aim',)))
            self.assertEqual([p.Offset_Internal for p in selected],[96,32])
        self.assertEqual(self.cache.totals['class_misses'],2)

    def test_live_animation_change_refuses_call_local_layout(self):
        anim,schema,props=self.animation_fixture()
        with self.cache.transaction(self.capture):
            self.cache.query_layout('owners',self.capture,anim)
            self.capture.anim_ref=lambda:obj('NewAnim',0x26001000)
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                self.cache.query_layout('owners',self.capture,anim)

    def test_bone_catalog_consumed_once_and_never_crosses_session(self):
        anim,schema,props=self.animation_fixture()
        mesh=self.capture.mesh_ref();pawn=self.capture.bound()[1]
        asset=obj('SkeletalMesh',0x29000000)
        pc,cam=obj('PC',0x30000000),obj('Camera',0x31000000)
        self.mod._get_runtime=lambda:(pc,pawn,cam)
        calls=[]
        mesh.GetNumBones=lambda:3
        mesh.GetSkeletalMeshAsset=lambda:asset
        mesh.GetBoneName=lambda i:calls.append(i) or ('Root','Head','Spine')[i]
        first=self.cache.bone_names('head',self.capture,mesh,3)
        second=self.cache.bone_names('visual',self.capture,mesh,3)
        self.assertEqual(first,second);self.assertEqual(len(calls),3)
        self.cache.bone_names('visual',self.capture,mesh,3)
        self.assertEqual(len(calls),6)
        self.cache.bone_names('head',self.capture,mesh,3)
        self.sup.child=S(mod=self.mod,updates=self.updates,active=True)
        self.cache.bone_names('visual',self.sup.child,mesh,3)
        self.assertEqual(len(calls),12)

class VehicleTests(unittest.TestCase):
    def setUp(self):
        self.pc = obj('OakPlayerController',0x20000000,bShowMouseCursor=False)
        self.pawn = obj('OakCharacter',0x20001000)
        self.camera = obj('OakPlayerCameraManager',0x20002000)
        self.vehicle = obj('OakVehicle',0x21000000,DriverPawn=self.pawn)
        self.pc.PersonalVehicleState = S(Vehicle=self.vehicle)
        self.runtime = (self.pc,self.pawn,self.camera)
        self.updates = S(is_game_thread=lambda:True,_owner=S(active=True))
        self.mod = S(_get_runtime=lambda:self.runtime,_third_person_enabled=True,
                     _ads_active=False,_shop_camera_active=False,_ladder_active=False,_slide_active=False)
        self.sup = S(mod=self.mod,updates=self.updates,active=True,child=None)
        self.mod._player_omnidirectional_gameplay = self.sup
        self.owner = VehicleHandoff(self.sup)
        self.sup.vehicle = self.owner
        self.air = ExitAir(self.owner)
        self.owner.air = self.air

    def test_paired_own_exit_only_and_nested_restart_invalidates(self):
        self.runtime = self.pc,self.vehicle,self.camera
        self.air.frame(*self.runtime)
        args = S(NewPawn=self.pawn)
        self.air.restart('PRE',self.pc,args)
        self.assertIsNone(self.air.ticket)
        self.runtime = self.pc,self.pawn,self.camera
        self.air.restart('POST',self.pc,args)
        self.assertTrue(self.air.ticket['confirmed'])
        self.air.restart('PRE',self.pc,args)
        self.assertIsNone(self.air.ticket)

    def test_foreign_driver_never_mints_ticket(self):
        self.vehicle.DriverPawn = obj('OtherCharacter',0x21001000)
        self.runtime = self.pc,self.vehicle,self.camera
        self.air.frame(*self.runtime)
        args = S(NewPawn=self.pawn)
        self.air.restart('PRE',self.pc,args)
        self.runtime = self.pc,self.pawn,self.camera
        self.air.restart('POST',self.pc,args)
        self.assertIsNone(self.air.ticket)

    def test_new_controller_invalidates_existing_vehicle_worker(self):
        self.runtime = obj('OakPlayerController',0x23000000),self.pawn,self.camera
        self.owner.frame()
        self.assertFalse(self.owner.active)
        self.assertIsNone(self.sup.vehicle)
        self.assertFalse(self.air.active)

    def test_disable_disarms_all_before_attempting_each_cleanup_and_retry(self):
        order=[]
        class Worker:
            control=[1]
            def disarm(self):self.control[0]=0;order.append('disarm')
            def stop(self):
                order.append('stop')
                if self.fail:raise RuntimeError('foreign patch')
        a,b=Worker(),Worker();a.fail=True;b.fail=False
        self.owner.summon,self.owner.exit=a,b
        with self.assertRaisesRegex(RuntimeError,'cleanup incomplete'):self.owner.stop()
        self.assertEqual(order, ['disarm','disarm','stop','stop'])
        self.assertFalse(self.owner.active)
        a.fail=False;self.owner.stop()

    def test_original_gap_ticket_closes_at_air_handoff(self):
        e = ExitFacing.__new__(ExitFacing)
        e.owner,e.mod,e.pawn_ref,e.vehicle_ref=self.owner,self.mod,lambda:self.pawn,lambda:self.vehicle
        e.control,e.gap_control=[0]*16,[0]*16
        e.gap_seat_open=True;e.consumed=1
        self.mod._third_person_pushed=True;self.mod._vehicle_camera_active=False
        m=S(MovementMode=3,CustomMovementMode=0,bWantsToDash=False,bWantsToSprint=False,bWantsToStartSprinting=False,bIsSprinting=False)
        self.pc.Pawn=self.pawn;self.pawn.IsCharacterDashing=lambda:False
        self.camera.CameraModeState=S(bIsTransitioning=False)
        self.camera.CameraModeInputs=S(ViewTarget=self.pawn)
        self.camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        self.air.ticket=dict(confirmed=True,character=lambda:self.pawn,vehicle=lambda:self.vehicle)
        e.gap_publish(self.pc,self.pawn,self.camera,m)
        self.assertEqual(e.gap_control[0],1)
        self.air.cancel('CONSUMED_BY_AIR_REBIND')
        e.gap_publish(self.pc,self.pawn,self.camera,m)
        self.assertEqual(e.gap_control[0],0)
        self.assertFalse(e.gap_seat_open)

    def test_native_templates_have_reviewed_fingerprints(self):
        from BL4ThirdPersonPOC.omni import vehicle_summon as s, vehicle_exit as e
        for module,name,digest in ((s,'TEMPLATE',s.TEMPLATE_HASH),(s,'POSSESSION_TEMPLATE',s.POSSESSION_TEMPLATE_HASH),
                (e,'PREFIX',e.PREFIX_HASH),(e,'GAP_PREFIX',e.GAP_PREFIX_HASH)):
            self.assertEqual(hashlib.sha256(getattr(module,name)).hexdigest(),digest)

    def test_hybrid_persisted_true_is_inactive_in_qa(self):
        mod=S(HYBRID_ADS_AVAILABLE=False,omni_hybrid_ads=S(value=True))
        self.assertFalse(hybrid_ads.option_enabled(mod))

if __name__ == '__main__': unittest.main()
