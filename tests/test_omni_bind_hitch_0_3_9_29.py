"""0.3.9.29: staged bind, hitch log, cheaper rebind, one combat read per callback."""
import unittest
from types import SimpleNamespace as S
from unittest.mock import Mock, patch

import support
import BL4ThirdPersonPOC.omni.grenade_facing as gf
import BL4ThirdPersonPOC.omni.vehicle_exit as vx
from BL4ThirdPersonPOC.omni import hitch
from BL4ThirdPersonPOC.omni.rebind_cache import RebindCache
from BL4ThirdPersonPOC.omni.session import GameplaySession


def staged_session():
    session, _ = support.session()
    session.mod._third_person_enabled = True
    session.active = True
    session.staged_bind = True
    for flag in ('slide_ready', 'vector_ready', 'sprint_ready', 'route_ready', 'ready', 'entry_ready'):
        setattr(session, flag, False)
    session.mesh_ref = None
    done = []

    def binder(name):
        def run():
            done.append(name)
            if name == 'visual':
                session.mesh_ref = lambda: None
            else:
                setattr(session, dict(slide='slide_ready', vector='vector_ready', sprint='sprint_ready',
                                      route='route_ready', root='ready', entries='entry_ready')[name], True)
        return run
    for name in GameplaySession.BIND_STEPS:
        setattr(session, '_bind_' + name, binder(name))
    objects = (S(), S(IsCharacterDashing=lambda: False), S(), S())
    session.bound = lambda: objects
    session.inputs = S(begin_frame=lambda **kw: None, end_frame=lambda: None)
    session.classify_handoff = Mock(return_value=('RUN', None))
    session.disarm_ground_vector = lambda: None
    session.ground_clip_originals = []
    session._ground_pose_frame = Mock()
    session.finish = Mock()
    return session, done


class StagedBindTests(unittest.TestCase):
    def test_one_step_per_run_update_in_former_order_then_pipeline(self):
        session, done = staged_session()
        for count in range(1, len(GameplaySession.BIND_STEPS) + 1):
            session.frame(None, None, None, None)
            self.assertEqual(len(done), count)
            session._ground_pose_frame.assert_not_called()
        self.assertEqual(tuple(done), GameplaySession.BIND_STEPS)
        self.assertEqual(tuple(session.report['bind_steps']), GameplaySession.BIND_STEPS)
        session.frame(None, None, None, None)
        session._ground_pose_frame.assert_called_once()
        self.assertFalse(session.staged_bind)
        session.finish.assert_not_called()

    def test_paused_updates_keep_the_original_pipeline(self):
        session, done = staged_session()
        session.classify_handoff.return_value = ('PAUSE', 'AIRBORNE')
        session.frame(None, None, None, None)
        self.assertEqual(done, [])
        session._ground_pose_frame.assert_called_once()

    def test_failed_step_stops_with_its_own_reason_and_skips_pipeline(self):
        session, done = staged_session()
        session._bind_slide = Mock(side_effect=RuntimeError('asset missing'))
        session.frame(None, None, None, None)
        session.finish.assert_called_once_with('BIND_SLIDE_FAILED')
        session._ground_pose_frame.assert_not_called()
        self.assertIn('Bind step slide', session.report['errors'][-1])

    def test_sessions_without_install_keep_lazy_first_update(self):
        session, done = staged_session()
        session.staged_bind = False
        session.frame(None, None, None, None)
        self.assertEqual(done, [])
        session._ground_pose_frame.assert_called_once()


class HitchLogTests(unittest.TestCase):
    def setUp(self):
        hitch.RECENT.clear()
        hitch._state.update(current=None, printed=0, total=0, worst_ms=0.0)
        self.logged = []
        self.patch = patch.object(hitch._sdk_logging, 'warning', side_effect=self.logged.append)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def run_root(self, durations):
        clock = iter(durations)

        @hitch.root('gameplay')
        def callback():
            with hitch.step('bind.visual'):
                pass
            with hitch.step('input.mapping_scan'):
                pass
        with patch.object(hitch, 'perf_counter_ns', side_effect=lambda: next(clock)):
            callback()

    def test_fast_callback_records_nothing(self):
        # root start, two steps (start/end each), root end: 3 ms total
        self.run_root([0, 100, 200, 300, 400, 3_000_000])
        self.assertEqual(list(hitch.RECENT), [])
        self.assertEqual(self.logged, [])

    def test_slow_callback_lists_slowest_steps_first(self):
        self.run_root([0, 0, 2_000_000, 2_000_000, 9_000_000, 12_000_000])
        row = hitch.RECENT[-1]
        self.assertEqual(row['callback'], 'gameplay')
        self.assertEqual(row['ms'], 12.0)
        self.assertEqual([name for name, _ in row['steps']], ['input.mapping_scan', 'bind.visual'])
        self.assertIn('[OmniHitch] gameplay 12.0 ms: input.mapping_scan 7.0, bind.visual 2.0', self.logged[0])

    def test_console_lines_are_capped_but_counted(self):
        for _ in range(hitch.MAX_CONSOLE + 5):
            self.run_root([0, 0, 1, 1, 2, 10_000_000])
        self.assertEqual(len(self.logged), hitch.MAX_CONSOLE)
        self.assertEqual(hitch.snapshot()['total'], hitch.MAX_CONSOLE + 5)

    def test_step_outside_a_root_is_free(self):
        with hitch.step('anything'):
            pass
        self.assertIsNone(hitch._state['current'])


class BindDietTests(unittest.TestCase):
    def install_session(self, bones, diagnostics=False):
        session, _ = support.session()
        session.collect_pose_diagnostics = diagnostics
        index = {name: i for i, name in enumerate(bones)}
        described = dict(_path_name=lambda: '/Test/Object', Class=S(_path_name=lambda: '/Test/Class'))
        mesh = S(**described, GetNumBones=lambda: len(bones), GetBoneName=lambda i: bones[i],
                 GetSocketRotation=lambda *a: None, K2_GetComponentRotation=lambda: None,
                 GetBoneIndex=Mock(side_effect=lambda name: index.get(name, -1)))
        node = S(RotationChannelName=S(TagName='RotationChannel.Aim'), ALPHA=1., BlendWeight=1.,
                 AlphaInputType=0, bInvertAlpha=False, BlendSpaceKey=None, BlendSpace=None)
        anim = S(**described, AimYaw=0., AimPitch=0., AimEnableAlpha=1., HeadEnableAlpha=1.,
                 **{name: node for name in GameplaySession.AIM_NODES})
        mesh.AnimScriptInstance = anim
        session.mod._get_runtime = lambda: (S(), S(Mesh=mesh), S())
        session._slide_state_install = lambda: None
        return session, mesh

    def test_production_checks_reviewed_bones_by_index_only(self):
        bones = ['Other%d' % i for i in range(200)] + list(GameplaySession.BONE_NAMES)
        session, mesh = self.install_session(bones)
        with patch('BL4ThirdPersonPOC.omni.session.bone_names', side_effect=AssertionError('catalog')):
            session.install()
        self.assertEqual(mesh.GetBoneIndex.call_count, len(GameplaySession.BONE_NAMES))
        self.assertTrue(session.staged_bind)

    def test_missing_reviewed_bone_still_fails_closed(self):
        session, _ = self.install_session(['Root', 'Spine5', 'Neck', 'Head'])
        with self.assertRaisesRegex(RuntimeError, 'bones missing'):
            session.install()

    def test_pose_diagnostics_keep_the_full_catalog(self):
        bones = list(GameplaySession.BONE_NAMES)
        session, mesh = self.install_session(bones, diagnostics=True)
        with patch('BL4ThirdPersonPOC.omni.session.bone_names', return_value=tuple(bones)) as names:
            session.install()
        names.assert_called_once()
        mesh.GetBoneIndex.assert_not_called()

    def test_rotate_schema_scanned_once_per_movement_class(self):
        supervisor = S(rebind_cache=RebindCache(S(mod=S(), updates=S())))
        cls = S(_get_address=lambda: 0x700)
        scans = []

        def session_for(movement_class):
            session = GameplaySession.__new__(GameplaySession)
            session.lifecycle_supervisor = supervisor
            session.rotate_schema_checked = False
            session.report = {}

            def scan(movement):
                scans.append(movement)
                session.report['rotate_state_schema'] = dict(offset=12240)
                session.rotate_schema_checked = True
            session._scan_rotate_schema = scan
            return session, S(Class=movement_class)
        first, movement = session_for(cls)
        first.validate_rotate_schema(movement)
        second, movement = session_for(cls)
        second.validate_rotate_schema(movement)
        self.assertEqual(len(scans), 1)
        self.assertTrue(second.report['rotate_state_schema']['reused_for_same_class'])
        third, movement = session_for(S(_get_address=lambda: 0x701))
        third.validate_rotate_schema(movement)
        self.assertEqual(len(scans), 2)


class SharedInputReaderTests(unittest.TestCase):
    def sample_install(self, shared):
        session, subscriptions = support.session()
        pc = S(bShowMouseCursor=False, GetControlRotation=lambda: None,
               _path_name=lambda: '/T/pc', Class=S(_path_name=lambda: '/T/C'))
        movement = S(MovementMode=1, _path_name=lambda: '/T/m', Class=S(_path_name=lambda: '/T/C'))
        pawn = S(Class=S(Name='OakCharacter', _path_name=lambda: '/T/C'), OakCharacterMovement=movement,
                 K2_GetActorRotation=lambda: None, GetLastMovementInputVector=lambda: None,
                 _path_name=lambda: '/T/p')
        camera = S(GetActorCameraMode=lambda p: 'ThirdPerson', GetCameraRotation=lambda: None,
                   _path_name=lambda: '/T/c', Class=S(_path_name=lambda: '/T/C'))
        session.updates._owner = S(active=True, live_widget=lambda: object())
        session.mod.__dict__.update(_get_runtime=lambda: (pc, pawn, camera), _third_person_enabled=True,
                                    _third_person_pushed=True)
        session.lifecycle_supervisor = S(input_owner=shared)
        with patch('BL4ThirdPersonPOC.omni.session.NativeBindings') as fresh:
            session._sample_install()
        return session, fresh, pc

    def test_reuses_complete_reader_of_the_same_controller(self):
        shared = S(matches=lambda pc: True, complete=True)
        session, fresh, _ = self.sample_install(shared)
        self.assertIs(session.inputs, shared)
        fresh.assert_not_called()

    def test_other_or_incomplete_reader_gets_a_fresh_full_scan(self):
        for shared in (S(matches=lambda pc: False, complete=True), S(matches=lambda pc: True, complete=False), None):
            with self.subTest(shared=shared):
                session, fresh, pc = self.sample_install(shared)
                fresh.assert_called_once_with(pc)
                fresh.return_value.refresh.assert_called_once_with(require_complete=True)


class OncePerCallbackTests(unittest.TestCase):
    def test_handler_validated_once_inside_a_callback(self):
        session = GameplaySession.__new__(GameplaySession)
        handler = object()
        session._validate_handler = Mock(return_value=handler)
        session.open_callback_scope()
        self.assertIs(session.validate_handler(), handler)
        self.assertIs(session.validate_handler(), handler)
        session._validate_handler.assert_called_once()
        session.close_callback_scope()
        session.validate_handler()
        self.assertEqual(session._validate_handler.call_count, 2)

    def test_combat_observed_once_per_callback(self):
        session = GameplaySession.__new__(GameplaySession)
        session.updates = S(is_game_thread=lambda: True)
        weapon = S(CurrentState='Active')
        anim = S(bIsFiring=False, bIsReloading=False)
        mesh = S(AnimScriptInstance=anim)
        movement = S(MovementMode=1, CustomMovementMode=0, bIsSprinting=False, bWantsToSprint=False)
        pawn = S(Mesh=mesh, bIsCrouched=False)
        camera = S(CameraModeInputs=S(Weapon=weapon))
        pc = S(bShowMouseCursor=False)
        session.bound = lambda: (pc, pawn, camera, movement)
        session.combat_refs = (lambda: mesh, lambda: anim, lambda: weapon)
        session.inputs = S(snapshot=lambda pc: dict(fire=False, zoom=False))
        session.mod = S(_ads_active=False, _third_person_enabled=True, _slide_active=False)
        session.collect_pose_diagnostics = False
        session.report = dict(combat_transitions=[])
        session.combat, session.started = {}, 0.
        session.read_throw = Mock(return_value=False)
        with patch('BL4ThirdPersonPOC.omni.animation.observe_hybrid_scope') as hybrid:
            session.open_callback_scope()
            session.read_combat()
            session.read_combat()
            session.close_callback_scope()
            self.assertEqual(session.read_throw.call_count, 1)
            self.assertEqual(hybrid.call_count, 1)
            session.read_combat()
            self.assertEqual(session.read_throw.call_count, 2)


class GrenadeClassTests(unittest.TestCase):
    def facing(self):
        facing = gf.GrenadeFacing.__new__(gf.GrenadeFacing)
        return facing

    def test_loaded_class_is_compared_by_identity(self):
        cls = S(_path_name=Mock(return_value=gf.SCRIPT_CLASS), _get_address=lambda: 0x5C1)
        other = S(_path_name=Mock(return_value='/Game/Other.Other_C'), _get_address=lambda: 0x5C2)
        pawn = S()
        mine = S(Class=cls, MyActor=pawn)
        rows = [S(Class=other, MyActor=pawn), mine, None]
        pawn.TrickData = S(InstancedScripts=rows)
        facing = self.facing()
        with patch.object(gf.unrealsdk, 'find_class', create=True, return_value=cls):
            self.assertEqual(facing.scripts(pawn), [mine])
            self.assertEqual(facing.scripts(pawn), [mine])
        other._path_name.assert_not_called()

    def test_unloaded_class_keeps_path_check_and_learns_from_first_instance(self):
        cls = S(_path_name=Mock(return_value=gf.SCRIPT_CLASS), _get_address=lambda: 0x5C1)
        pawn = S()
        mine = S(Class=cls, MyActor=pawn)
        pawn.TrickData = S(InstancedScripts=[mine])
        facing = self.facing()
        with patch.object(gf.unrealsdk, 'find_class', create=True, side_effect=ValueError('not loaded')):
            self.assertEqual(facing.scripts(pawn), [mine])
            calls = cls._path_name.call_count
            self.assertEqual(facing.scripts(pawn), [mine])
        self.assertEqual(cls._path_name.call_count, calls)


class ExitFacingTests(unittest.TestCase):
    """0.3.9.29.1: a parked/settling vehicle keeps its body yaw on exit."""

    def facing(self):
        exit_ = vx.ExitFacing.__new__(vx.ExitFacing)
        exit_.seated, exit_.vehicle_ref, exit_.sequence, exit_.frames = False, None, 0, 0
        exit_.owner = S(summon=None)
        exit_.mod = S(_ads_active=False)
        exit_.pawn_ref = lambda: 'character'
        exit_.control = [0] * 24
        return exit_

    def publish(self, exit_, velocity, body_yaw=90.):
        vehicle = getattr(exit_, 'test_vehicle', None)
        if vehicle is None:
            vehicle = exit_.test_vehicle = S(Class=S(), _get_address=lambda: 0x700000, DriverPawn='character')
        vehicle.K2_GetActorRotation = lambda: S(Pitch=0., Yaw=body_yaw, Roll=0.)
        vehicle.GetVelocity = lambda: S(X=velocity[0], Y=velocity[1], Z=0.)
        pc = S(PersonalVehicleState=S(Vehicle=vehicle), Pawn=vehicle, bShowMouseCursor=False,
               GetControlRotation=lambda: S(Yaw=0.))
        camera = S(CameraModeState=S(bIsTransitioning=False), CameraModeInputs=S(ViewTarget=vehicle))
        exit_.publish_vehicle(pc, vehicle, camera)
        return exit_

    def test_settling_vehicle_keeps_body_yaw(self):
        for velocity in ((-3., 0.), (0., -40.), (1e-4, 1e-4), (0., 0.)):
            with self.subTest(velocity=velocity):
                exit_ = self.publish(self.facing(), velocity)
                self.assertEqual(exit_.last_yaw, 90.)
                self.assertEqual(exit_.source, 'vehicle_body_below_travel_speed')

    def test_driving_uses_travel_direction(self):
        exit_ = self.publish(self.facing(), (0., 600.), body_yaw=75.)
        self.assertAlmostEqual(exit_.last_yaw, 90.)
        self.assertEqual(exit_.source, 'vehicle_travel_direction')
        exit_ = self.publish(self.facing(), (-400., 0.), body_yaw=0.)
        self.assertAlmostEqual(abs(exit_.last_yaw), 180.)

    def test_stopping_after_driving_returns_to_body_yaw(self):
        exit_ = self.publish(self.facing(), (600., 0.), body_yaw=10.)
        self.assertAlmostEqual(exit_.last_yaw, 0.)
        exit_ = self.publish(exit_, (20., 0.), body_yaw=10.)
        self.assertEqual(exit_.last_yaw, 10.)

    def test_seat_start_writes_one_trace_line(self):
        with patch.object(hitch, 'note') as note:
            exit_ = self.publish(self.facing(), (0., 0.))
            self.publish(exit_, (0., 0.))
        note.assert_called_once()
        self.assertIn('seated vehicle_yaw=90', note.call_args[0][1])

    def test_trace_value_never_raises(self):
        self.assertEqual(hitch.value(lambda: 1 / 0), '?')
        self.assertEqual(hitch.value(lambda: 12.6), '13')


if __name__ == '__main__':
    unittest.main()
