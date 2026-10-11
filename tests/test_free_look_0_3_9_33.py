"""Angular policy, real publisher/frame, and executable x64 prefix verification."""
import ctypes as C
import hashlib
import math
import mmap
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
from types import SimpleNamespace as S
import unittest
from concurrent.futures import ThreadPoolExecutor
import support
from BL4ThirdPersonPOC.omni.free_look import pose_input, publish
from BL4ThirdPersonPOC.omni.native_free_look import (
    NativeFreeLookAim, FREE_LOOK_PREFIX, FREE_LOOK_HASH)
from BL4ThirdPersonPOC.omni.session import GameplaySession

ROOT = Path(__file__).resolve().parents[1]


def packed(yaw, alpha):
    return struct.unpack('<Q', struct.pack('<ff', yaw, alpha))[0]


def publisher_session():
    session = S(mod=S(_third_person_enabled=True), active=True, free_look_context=True, impulse_index=1,
                cycle_start=None, ground_circle_previous_dash=False,
                frames=10, combat=dict(active=False), collect_pose_diagnostics=False)
    session.aim_native = NativeFreeLookAim(session)
    session.aim_native.control[0] = session.aim_native.crouch_control[0] = 1
    sample = dict(update_index=10, normal_tps_sample=True, combat=dict(active=False),
                  actor_rotation=dict(Yaw=0), camera_rotation=dict(Yaw=75))
    session.report = dict(samples=[sample], errors=[])
    return session, sample


class PosePolicyTests(unittest.TestCase):
    def test_rear_sector_keeps_pitch_and_limits_yaw(self):
        for value in (-60, -45, -35, -10, 0, 10, 35, 45, 60):
            yaw, alpha = pose_input(value, 0)
            self.assertEqual(alpha, 1)
            self.assertEqual(yaw, max(-35, min(35, value)))

    def test_side_and_front_are_neutral(self):
        for value in (-180, -150, -90, 90, 150, 180, 270):
            self.assertEqual(pose_input(value, 0), (0, 0))

    def test_fade_is_symmetric_monotonic_and_continuous(self):
        previous = 1
        for i in range(601, 901):
            value = i / 10
            yaw, alpha = pose_input(value, 0)
            neg_yaw, neg_alpha = pose_input(-value, 0)
            self.assertAlmostEqual(neg_yaw, -yaw, places=12)
            self.assertAlmostEqual(neg_alpha, alpha, places=13)
            self.assertLessEqual(alpha, previous)
            self.assertLessEqual(abs(yaw), 35)
            previous = alpha
        self.assertEqual(pose_input(75, 0), (17.5, .5))
        for boundary in (35, 60, 90):
            a = pose_input(boundary - 1e-5, 0)
            b = pose_input(boundary + 1e-5, 0)
            self.assertLess(max(abs(x-y) for x,y in zip(a,b)), 1e-4)

    def test_body_relative_and_wrap_do_not_depend_on_world_heading(self):
        self.assertEqual(pose_input(179, -179), (-2, 1))
        self.assertEqual(pose_input(-179, 179), (2, 1))
        self.assertEqual(pose_input(720 + 75, 720), (17.5, .5))

    def test_invalid_inputs_fail_before_publication(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(RuntimeError, 'nonfinite'):
                pose_input(value, 0)
            with self.assertRaisesRegex(RuntimeError, 'nonfinite'):
                pose_input(0, value)


class PublisherTests(unittest.TestCase):
    def test_slam_closes_both_legacy_and_angular_aim_modes(self):
        for old in (1, 2):
            session, sample = publisher_session()
            session.ground_slam_pose_native = True
            session.aim_native.control[0] = session.aim_native.crouch_control[0] = old
            session.aim_native.control[5] = packed(0., 0.)
            publish(session)
            self.assertEqual((session.aim_native.control[0], session.aim_native.crouch_control[0]), (0, 0))

    def test_publishes_one_packed_word_and_does_not_access_sdk(self):
        session, sample = publisher_session()
        session.bound = lambda: self.fail('extra SDK access')
        publish(session)
        for control in (session.aim_native.control, session.aim_native.crouch_control):
            self.assertEqual(control[0], 2)
            self.assertEqual(control[5], packed(17.5, .5))
        self.assertNotIn('free_look', sample)

    def test_uses_actual_post_follow_body_for_standing_and_crouch(self):
        for field, key in (('follow', 'immediate_actor_rotation'),
                           ('crouch_follow', 'actor_after')):
            session, sample = publisher_session()
            sample[field] = {key: dict(Yaw=70)}
            publish(session)
            self.assertEqual(session.aim_native.control[5], packed(5, 1))

    def test_diagnostics_only_adds_current_sample_pose(self):
        session, sample = publisher_session()
        session.collect_pose_diagnostics = True
        publish(session)
        self.assertEqual(sample['free_look']['yaw_input'], 17.5)
        self.assertEqual(sample['free_look']['pitch_alpha'], .5)

    def test_closed_gates_are_not_reopened(self):
        session, _ = publisher_session()
        session.aim_native.crouch_control[0] = 0
        publish(session)
        self.assertEqual(session.aim_native.control[0], 2)
        self.assertEqual(session.aim_native.crouch_control[0], 0)
        self.assertEqual(session.aim_native.crouch_control[5], 0)

    def test_rejected_contexts_keep_legacy_special_mode_and_closed_gate(self):
        for reason in ('inactive', 'context', 'impulse', 'dash', 'cycle',
                       'sample_combat', 'combat', 'abnormal', 'stale', 'no_sample'):
            session, sample = publisher_session()
            session.aim_native.control[0] = 2
            session.aim_native.crouch_control[0] = 0
            if reason == 'inactive': session.active = False
            elif reason == 'context': session.free_look_context = False
            elif reason == 'impulse': session.impulse_index = None
            elif reason == 'dash': session.ground_circle_previous_dash = True
            elif reason == 'cycle': session.cycle_start = 3
            elif reason == 'sample_combat': sample['combat']['active'] = True
            elif reason == 'combat': session.combat['active'] = True
            elif reason == 'abnormal': sample['normal_tps_sample'] = False
            elif reason == 'stale': sample['update_index'] = 9
            elif reason == 'no_sample': session.report['samples'] = []
            publish(session)
            expected = 0 if reason in ('inactive', 'combat', 'sample_combat') else 1
            self.assertEqual(session.aim_native.control[0], expected, reason)
            self.assertEqual(session.aim_native.crouch_control[0], 0, reason)
            self.assertEqual(session.aim_native.control[5], 0, reason)

    def test_nonfinite_disarms_both_gates(self):
        session, sample = publisher_session()
        sample['camera_rotation']['Yaw'] = math.nan
        with self.assertRaisesRegex(RuntimeError, 'nonfinite'):
            publish(session)
        self.assertEqual(session.aim_native.control[0], 0)
        self.assertEqual(session.aim_native.crouch_control[0], 0)

    def test_stop_restores_owned_hook_and_closes_both_controls(self):
        session, _ = publisher_session()
        aim = session.aim_native
        operations = []
        session.updates = S(is_game_thread=lambda: True)
        session.mod._native_restore_hook = lambda hook: operations.append('restore')
        session.mod._native_release_hook = lambda hook: operations.append('release')
        aim.control[0] = aim.crouch_control[0] = 2
        aim.hook = dict(patch_attempted=True, control=aim.control)
        aim.stop()
        self.assertEqual(operations, ['restore', 'release'])
        self.assertIsNone(aim.hook)
        self.assertEqual((aim.control[0], aim.crouch_control[0]), (0,0))
        self.assertTrue(session.report['aim_native_restoration_verified'])

    def test_foreign_animation_is_rejected_by_inherited_owner_validation(self):
        session, _ = publisher_session()
        session.anim_ref = lambda: S(_get_address=lambda: 0x5000)
        session.anim_address = 0x4000
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            session.aim_native.validate()

    def test_real_frame_publishes_after_body_work_and_closes_input_scope(self):
        state, sample = publisher_session()
        session = GameplaySession.__new__(GameplaySession)
        session.__dict__.update(state.__dict__)
        session.busy = session.lifecycle_managed = False
        session.updates = S(is_game_thread=lambda: True)
        pawn = S(IsCharacterDashing=lambda: False)
        camera = S(GetActorCameraMode=lambda pawn: 'ThirdPerson')
        movement = S(MovementMode=1, CustomMovementMode=0)
        session.bound = lambda: (None, pawn, camera, movement)
        scope = []
        session.inputs = S(begin_frame=lambda **kw: scope.append('begin'),
                           end_frame=lambda: scope.append('end'))
        session.disarm_ground_vector = lambda: None
        session.ground_clip_originals = []
        def body(*args):
            session.free_look_context = True
            sample['follow'] = dict(immediate_actor_rotation=dict(Yaw=70))
        session._ground_pose_frame = body
        session.frame(None, None, None, None)
        self.assertEqual(session.aim_native.control[5], packed(5, 1))
        self.assertEqual(scope, ['begin', 'end'])
        self.assertFalse(session._callback_scope)

    def test_real_handoff_only_allows_run_or_non_dash_crouch(self):
        for action, reason, dash, expected in (
            ('RUN', None, False, True), ('PAUSE', 'CROUCHED', False, True),
            ('PAUSE', 'CROUCHED', True, False), ('PAUSE', 'AIRBORNE', False, False),
            ('PAUSE', 'SLIDE', False, False), ('PAUSE', 'SLIDE_EXIT', False, False),
            ('PAUSE', 'JUMP_INPUT', False, False), ('STOP', 'TPS_OR_UI_CHANGED', False, False)):
            session = GameplaySession.__new__(GameplaySession)
            session.active, session.busy = True, False
            session.updates = S(is_game_thread=lambda: True)
            session.bound = lambda: (None, None, None, None)
            session.classify_handoff = lambda *args: (action, reason)
            session.is_dashing = lambda pawn: dash
            session.finish = lambda *args: None
            session.paused_frame = session._dash_vector_frame = lambda *args: None
            session.handoff_reason = None
            session.report = dict(samples=[], errors=[])
            session._handoff_frame(None, None, None, None)
            self.assertEqual(session.free_look_context, expected, reason)


@unittest.skipUnless(platform.system() == 'Linux' and platform.machine() == 'x86_64'
                     and shutil.which('gcc') and shutil.which('objcopy'),
                     'executable native validation requires Linux x64 GNU tools')
class ExecutablePrefixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        directory = Path(cls.directory.name)
        sources = ROOT / 'docs/omni/native_validation'
        subprocess.run(['gcc', '-shared', '-fPIC', str(sources/'free_look_fixture.s'),
                        '-o', str(directory/'fixture.so')], check=True, capture_output=True)
        cls.lib = C.CDLL(str(directory/'fixture.so'))
        cls.lib.run_free_look.argtypes = [C.c_void_p] * 4
        cls.lib.run_free_look.restype = None
        cls.caller = C.cast(cls.lib.free_look_return, C.c_void_p).value
        subprocess.run(['gcc', '-c', str(sources/'free_look_prefix.s'),
                        '-o', str(directory/'prefix.o')], check=True, capture_output=True)
        subprocess.run(['objcopy', '-O', 'binary', '--only-section=.text',
                        str(directory/'prefix.o'), str(directory/'prefix.bin')], check=True)
        cls.assembled = (directory/'prefix.bin').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.aim = NativeFreeLookAim(S(mod=S()))
        for i, control in enumerate((self.aim.control, self.aim.crouch_control)):
            control[0], control[1], control[2] = 2, 0x10000 + i*16, self.caller
            control[5] = packed(17.5, .5)
        self.memory = mmap.mmap(-1, 4096, prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
        self.memory.write(self.aim.prefix_code() + b'\xc3')
        self.address = C.addressof(C.c_ubyte.from_buffer(self.memory))

    def tearDown(self):
        self.memory.close()

    def run_prefix(self, node=0x10000, pitch=40, null=False):
        vector = (C.c_double * 5)(1234, 140, pitch, 23, 4321)
        state = (C.c_ubyte * 128)()
        seed = bytes(range(48))
        C.memmove(state, seed, len(seed))
        address = C.addressof(vector)+8
        self.lib.run_free_look(self.address, node, None if null else address, C.addressof(state))
        raw = bytes(state)
        self.assertEqual(raw[:48], seed, 'XMM0-2 changed')
        self.assertEqual(struct.unpack_from('<Q',raw,48)[0], 0x1234567812345678)
        self.assertEqual(struct.unpack_from('<Q',raw,56)[0], 0x8765432187654321)
        self.assertEqual(struct.unpack_from('<Q',raw,64)[0], node)
        self.assertEqual(struct.unpack_from('<Q',raw,72)[0], 0 if null else address)
        self.assertEqual(raw[80:88], raw[88:96], 'stack changed')
        self.assertEqual(raw[96:104], raw[104:112], 'flags changed')
        self.assertEqual(raw[112:116], raw[116:120], 'MXCSR changed')
        self.assertEqual((vector[0], vector[3], vector[4]), (1234,23,4321))
        return tuple(vector)[1:3]

    def test_source_template_hash_and_publication_alignment(self):
        self.assertEqual(self.assembled, FREE_LOOK_PREFIX)
        self.assertEqual(hashlib.sha256(FREE_LOOK_PREFIX).hexdigest(), FREE_LOOK_HASH)
        self.assertEqual(hashlib.sha256(self.aim.PREFIX).hexdigest(), self.aim.HASH)
        self.assertEqual(len(self.aim.PREFIX), self.aim.PREFIX_SIZE)
        for control in (self.aim.control, self.aim.crouch_control):
            self.assertEqual((C.addressof(control)+40)%8, 0)
        self.assertIs(self.aim.control._slide_crouch_control, self.aim.crouch_control)

    def test_standing_and_crouch_only_touch_the_matching_node(self):
        self.assertEqual(self.run_prefix(), (17.5,20))
        self.assertEqual((self.aim.control[3],self.aim.crouch_control[3]), (1,0))
        self.aim.crouch_control[5] = packed(-35,1)
        self.assertEqual(self.run_prefix(node=0x10010,pitch=-50), (-35,-50))
        self.assertEqual((self.aim.control[3],self.aim.crouch_control[3]), (1,1))

    def test_legacy_zero_yaw_preserves_pitch_exactly(self):
        for control in (self.aim.control,self.aim.crouch_control): control[0] = 1
        for node in (0x10000,0x10010):
            self.assertEqual(self.run_prefix(node,pitch=-40), (0,-40))

    def test_disabled_unknown_mode_foreign_node_caller_and_null_leave_vector(self):
        for mode in (0,3):
            self.aim.control[0] = mode
            self.assertEqual(self.run_prefix(), (140,40))
        self.aim.control[0] = 2
        self.assertEqual(self.run_prefix(node=0x20000), (140,40))
        self.assertEqual(self.run_prefix(null=True), (140,40))
        self.aim.control[2] += 1
        self.assertEqual(self.run_prefix(), (140,40))
        self.assertEqual(self.aim.control[3],0)

    def test_front_view_neutralizes_both_axes_and_keeps_other_state(self):
        for camera in (90,120,180,270):
            self.aim.control[5] = packed(*pose_input(camera,0))
            self.assertEqual(self.run_prefix(pitch=-60), (0,0))

    def test_corrupt_packet_never_writes(self):
        for yaw, alpha in ((math.nan,1),(math.inf,1),(-math.inf,1),
                           (36,1),(-36,1),(5,math.nan),(5,math.inf),(5,-.1),(5,1.1)):
            self.aim.control[5] = packed(yaw,alpha)
            self.assertEqual(self.run_prefix(),(140,40))
        self.assertEqual(self.aim.control[3],0)

    def test_invalid_original_pitch_never_writes(self):
        for pitch in (math.nan,math.inf,-math.inf,181,-181):
            result = self.run_prefix(pitch=pitch)
            self.assertEqual(result[0],140)
            self.assertTrue(math.isnan(result[1]) if math.isnan(pitch) else result[1] == pitch)
        self.assertEqual(self.aim.control[3],0)

    def test_native_angular_sweep_matches_publisher_policy(self):
        for value in range(-180,181):
            yaw, alpha = pose_input(value,0)
            self.aim.control[5] = packed(yaw,alpha)
            actual = self.run_prefix(pitch=52)
            self.assertAlmostEqual(actual[0],yaw,places=5)
            self.assertAlmostEqual(actual[1],52*alpha,places=5)

    def test_parallel_dispatch_counters_and_packets_remain_coherent(self):
        values = (packed(-20,.25), packed(35,.75))
        def worker(index):
            for _ in range(500):
                if index == 0:
                    self.aim.control[5] = values[_%2]
                result = self.run_prefix()
                self.assertIn(result, ((-20,10),(35,30),(17.5,20)))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(worker,range(4)))
        self.assertEqual(self.aim.control[3],2000)
        self.assertEqual(self.aim.control[4],2000)


if __name__ == '__main__':
    unittest.main()
