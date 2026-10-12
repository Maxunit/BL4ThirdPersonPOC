"""Read-only public IdleTurns inputs and bounded original-code reconstruction."""
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import Mock,patch
import unittest
import ground_slam_exit_probe_scenario as exit_probe
import ground_slam_rotation_probe_scenario as rotation
from BL4ThirdPersonPOC.omni.native_idle_scope import IDLE_NAMES,ScopedIdleRoot,ScopedIdleUpdate

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_idle_inputs_capture.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_idle_inputs_capture'


class IdleInputTests(exit_probe.ExitTests):
    def setUp(self):
        self.source_patch=patch.multiple(rotation,SOURCE=SOURCE,KEY=KEY)
        self.source_patch.start()
        rotation.RotationTests.setUp(self)
        rotation.facing.phase.mod.MOD_VERSION='0.3.9.40'
        self.native.control[0]=self.native.control[7]=1
        self.native.control[8]=self.native.base+0x2e2e17
        self.child.report['ground_slam_heading_hold']=dict(enabled=True,update=1)
        self.child.ground_slam_pose_native=False
        self.anim.AimEnableAlpha=1.
        self.world.movement.CurrentRotateToState=S(CommandData=S(
            Duration=.2,InterpSpeed=1.,MaxYawRate=180.,MaxPitchRate=0.,
            TargetLocation=S(X=0.,Y=0.,Z=0.),TargetActor=None,TargetSocket='None',
            bFreezeRotation=False,bUseEasing=True,bUpdateCamera=False))

    def arm(self):
        c=self.execute();c.armed_at=0;self.tick()
        self.assertTrue(c.active)
        self.assertEqual(self.native.slide_control[0],0)
        return c

    def test_native_recording_does_not_spend_buffer_on_ordinary_standing(self):
        c=self.arm();self.tick();self.assertEqual(self.native.slide_control[0],0)
        self.world.pawn.slam=True;self.child.ground_slam_pose_native=True
        self.tick();self.assertEqual(self.native.slide_control[0],1)
        self.world.pawn.slam=False;self.child.ground_slam_pose_native=False
        self.tick();self.assertEqual(self.native.slide_control[0],0)
        self.execute();self.saved(c)

    def test_cleanup_requires_game_thread_and_can_be_retried(self):
        c=self.arm();self.world.pawn.slam=True;self.child.ground_slam_pose_native=True
        self.tick()
        with patch.object(rotation.runtime_updates,'is_game_thread',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'game thread'):self.execute()
        self.assertTrue(c.active);self.assertTrue(self.producer.routes)
        self.execute();self.saved(c)
        self.assertEqual(self.native.slide_control[0],0)

    def bind_public_schema(self):
        fields=[S(Name=name,Class=S(Name=kind)) for name,kind in (
            ('Yaw','FloatProperty'),('CurrentInput','IntProperty'),
            ('ShouldTurn','BoolProperty'),('OpaquePose','StructProperty'))]
        typ=S(Name='GbxAnimNode_IdleTurns',_superfields=lambda:(),_properties=lambda:iter(fields))
        self.anim.Class._find=lambda name:S(Class=S(Name='StructProperty'),Struct=typ)
        for name in IDLE_NAMES:setattr(self.anim,name,S(Yaw=179.,CurrentInput=1,ShouldTurn=True))
        return fields

    def bind_code_fixture(self):
        self.code={};self.original={}
        for attr,cls,size in (('idle_update',ScopedIdleUpdate,0x3d6),('idle_native',ScopedIdleRoot,512)):
            worker=cls(self.child);worker.validate=Mock()
            offset=worker.TARGET-worker.POSE_TARGET
            raw=bytearray(b'\xCC'*size)
            raw[offset:offset+len(worker.PROLOGUE)]=worker.PROLOGUE
            self.original[worker.POSE_TARGET]=bytes(raw)
            owned=b'\x90'*len(worker.PROLOGUE)
            raw[offset:offset+len(owned)]=owned
            worker.hook=dict(target=self.native.base+worker.TARGET,patch=owned,
                             original=worker.PROLOGUE,restored=False)
            self.code[self.native.base+worker.POSE_TARGET]=bytes(raw)
            setattr(self.child,attr,worker)
        self.old_read=self.native.read
        def read(address,size):
            if address in self.code:
                self.child.report['native_reads']=self.child.report.get('native_reads',0)+1
                data=self.code[address]
                if len(data)!=size:raise RuntimeError('Short code read')
                return data
            return self.old_read(address,size)
        self.native.read=read
        info=S(State=0x1000,Type=0x1000000,Protect=0x20,
               BaseAddress=self.native.base,RegionSize=0x3000000)
        self.query=patch.object(rotation.facing.phase.mod,'_native_query',return_value=info)
        self.query.start();self.addCleanup(self.query.stop)

    def test_public_turn_inputs_are_bounded_and_queried_without_node_writes(self):
        fields=self.bind_public_schema();c=self.arm();self.mode='GroundSlamExit'
        self.tick()
        first=c.report['samples'][-1]['idle_public_inputs']
        self.assertEqual(first['GbxAnimGraphNode_IdleTurns']['Yaw'],179.)
        self.assertNotIn('OpaquePose',first['GbxAnimGraphNode_IdleTurns'])
        for name in IDLE_NAMES:
            node=getattr(self.anim,name);node.Yaw=-179.;node.CurrentInput=2
        for _ in range(4):self.tick()
        last=next(r for r in reversed(c.report['samples']) if 'idle_public_inputs' in r)
        self.assertEqual(last['idle_public_inputs']['GbxAnimGraphNode_IdleTurns']['CurrentInput'],2)
        self.assertEqual(getattr(self.anim,'GbxAnimGraphNode_IdleTurns').Yaw,-179.)
        self.execute();r=self.saved(c)
        self.assertFalse(r['errors']);self.assertFalse(r['optional_errors'])
        self.assertEqual(r['game_writes'],0)

    def test_unbounded_schema_is_not_traversed(self):
        fields=self.bind_public_schema()
        fields.extend(S(Name='extra'+str(i),Class=S(Name='FloatProperty')) for i in range(257))
        c=self.arm();self.tick();self.execute();r=self.saved(c)
        self.assertTrue(all(x['status']=='UNAVAILABLE' for x in r['idle_public_schema'].values()))
        self.assertFalse(r['errors'])

    def bind_reviewed_private_fixture(self):
        import json,struct
        self.bind_code_fixture()
        fn=json.loads((Path(__file__).resolve().parent/'fixtures/slam_idle_update_1.10.2.json').read_text())
        worker=self.child.idle_update
        raw=bytearray(bytes.fromhex(fn['original_code_hex']))
        offset=worker.TARGET-worker.POSE_TARGET
        raw[offset:offset+len(worker.hook['patch'])]=worker.hook['patch']
        self.code[self.native.base+worker.POSE_TARGET]=bytes(raw)
        nodes=tuple((name,self.native.base+0x10000+i*0x400) for i,name in enumerate(sorted(IDLE_NAMES)))
        self.child.idle_native.scope_nodes=nodes
        self.private={}
        for name,address in nodes:
            value=bytearray(24);struct.pack_into('<2f',value,0,10.,-167.)
            value[8]=value[12]=value[20]=1
            struct.pack_into('<f',value,16,-177.)
            self.private[address+0x300]=bytes(value)
        old=self.native.read
        def read(address,size):
            if address in self.private:
                self.child.report['native_reads']=self.child.report.get('native_reads',0)+1
                assert size==24
                return self.private[address]
            return old(address,size)
        self.native.read=read

    def test_private_read_requires_reviewed_code_and_exact_owned_scope(self):
        self.bind_reviewed_private_fixture();before=dict(self.private)
        c=self.arm();self.tick();row=c.report['samples'][-1]
        data=row['idle_private_state']
        self.assertEqual(data['status'],'READ')
        self.assertEqual(len(data['nodes']),5)
        self.assertTrue(all(v['raw_input_minus_reference']==-177. for v in data['nodes'].values()))
        self.assertEqual(self.private,before)
        self.execute();r=self.saved(c)
        self.assertFalse(r['optional_errors'])
        self.assertEqual(r['game_writes'],0)

    def test_unreviewed_code_never_reads_private_offsets(self):
        self.bind_code_fixture();c=self.arm();self.tick()
        self.assertEqual(c.report['samples'][-1]['idle_private_state']['status'],'UNREVIEWED_LAYOUT')
        self.execute();self.saved(c)

    def test_original_code_reconstruction_does_not_change_live_code(self):
        self.bind_code_fixture();before=dict(self.code);c=self.arm()
        snapshot=c.report['idle_code_snapshot']
        self.assertEqual(snapshot['status'],'CAPTURED')
        self.assertEqual(len(snapshot['functions']),2)
        for fn in snapshot['functions']:
            self.assertEqual(bytes.fromhex(fn['original_code_hex']),self.original[int(fn['entry_rva'],16)])
        self.assertEqual(self.code,before)
        self.assertEqual(self.native.control[0],1);self.assertEqual(self.native.control[7],1)
        self.tick();self.execute();r=self.saved(c)
        self.assertEqual(r['native_patches_added'],0);self.assertEqual(r['game_writes'],0)

    def test_foreign_patch_is_not_reconstructed_or_modified(self):
        self.bind_code_fixture();worker=self.child.idle_native
        address=self.native.base+worker.POSE_TARGET
        data=bytearray(self.code[address]);data[worker.TARGET-worker.POSE_TARGET]=0xCC
        self.code[address]=bytes(data);before=dict(self.code)
        c=self.arm()
        self.assertEqual(c.report['idle_code_snapshot']['status'],'READ_FAILED')
        self.assertEqual(self.code,before);self.assertTrue(c.active)
        self.tick();self.execute();self.saved(c)


if __name__=='__main__':unittest.main()
