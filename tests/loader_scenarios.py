"""Scenarios executed in a fresh interpreter by test_loader_smoke.py."""
import json
import sys
import traceback

import loader_harness as h


def unreviewed():
    loader = h.load()
    h.set_build(False)
    h.enable_entry_points(loader)
    loader._on_enable()
    result = dict(
        hooks=sorted(map(list, h.HOOKS)),
        enabled_keybinds=[k.identifier for k in loader._MOD_KEYBINDS if k.is_enabled],
        enabled_commands=[c.cmd for c in loader._MOD_COMMANDS if c.enabled],
        inactive_logged=any('INACTIVE_UNREVIEWED_BUILD' in m for _, m in h.LOG),
    )
    loader._on_disable()
    result['errors_after_disable'] = [m for level, m in h.LOG if level == 'error'
                                      and 'INACTIVE_UNREVIEWED_BUILD' not in m]
    return result


def reviewed(omni_on):
    loader = h.load()
    h.set_build(True)
    loader.omni_movement_experimental.value = omni_on
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    from BL4ThirdPersonPOC import omni, runtime_updates, action_keys
    after_enable = dict(
        hooks=sorted('|'.join(map(str, key)) for key in h.HOOKS),
        omni_running=omni.is_running(loader),
        action_keys_running=action_keys._owner is not None and action_keys._owner.active,
        updates_routes=sorted('|'.join(map(str, key)) for key in runtime_updates._owner.routes),
        enable_errors=[m for level, m in h.LOG if level == 'error'],
    )
    # Console command path while enabled.
    loader.omni_movement_console.run('status')
    stage_log_start = len(h.LOG)
    loader._on_disable()
    after_disable = dict(
        hooks=sorted('|'.join(map(str, key)) for key in h.HOOKS),
        omni_running=omni.is_running(loader),
        action_keys_running=action_keys._owner is not None,
        runtime_updates_running=runtime_updates._owner is not None,
        disable_log=[(level, m) for level, m in h.LOG[stage_log_start:] if level in ('error', 'warning')],
    )
    return dict(after_enable=after_enable, after_disable=after_disable,
                status_logged=[m for _, m in h.LOG if 'OMNI_STATUS' in m])


def toggle_cycle():
    """Menu/console toggle: on -> off -> on, with option persistence semantics."""
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    from BL4ThirdPersonPOC import omni
    steps = []
    for value in (True, False, True):
        accepted = loader._set_omni_movement(value)
        steps.append(dict(requested=value, accepted=accepted,
                          option=loader.omni_movement_experimental.value,
                          running=omni.is_running(loader),
                          caption=loader._omni_movement_caption()))
    loader.omni_movement_console.run('diag on')
    steps.append(dict(diag_option=loader.omni_movement_diagnostics.value,
                      diag_runtime=omni.settings.diagnostics_enabled(),
                      running=omni.is_running(loader)))
    loader._on_disable()
    steps.append(dict(after_disable_running=omni.is_running(loader)))
    return steps


def from_sdkmod():
    """Import from the built zip (zipimport), as the Oak2 loader does."""
    archive = h.REPO / 'dist' / 'BL4ThirdPersonPOC.sdkmod'
    sys.path.remove(str(h.REPO))
    sys.path.insert(0, str(archive))
    loader = h.load()
    h.set_build(True)
    loader.omni_movement_experimental.value = True
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    loader.omni_movement_console.run('hybrid on')
    hybrid_on = loader.omni_hybrid_ads.value
    loader.omni_movement_console.run('hybrid off')
    hybrid_off = loader.omni_hybrid_ads.value
    loader.omni_movement_console.run('report')
    reports = [m for _, m in h.LOG if 'OMNI_REPORT json=' in m]
    loader._on_disable()
    return dict(loader_file=loader.__file__, hybrid_on=hybrid_on, hybrid_off=hybrid_off, report_logged=bool(reports),
                report_written=bool(reports) and str(h.SETTINGS) in reports[-1],
                hooks_after_disable=len(h.HOOKS))


def toggle_repair():
    """F5 while TPS is wanted but the game shows a settled Default camera."""
    from types import SimpleNamespace as S
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    camera = S(GetActorCameraMode=lambda pawn: 'Default', CameraModeState=S(bIsTransitioning=False),
               _get_address=lambda: 0x2000)
    pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: 0x1000)
    pc = S(bShowMouseCursor=False, _get_address=lambda: 0x3000)
    loader._get_runtime = lambda: (pc, pawn, camera)
    loader._is_vehicle_camera_view = lambda: False
    loader._third_person_enabled = True
    repairs = []
    loader._repair_third_person = lambda *, automatic: repairs.append(automatic) or True
    loader.toggle_third_person.callback()
    stage_source = open(h.REPO / 'BL4ThirdPersonPOC' / 'camera_events.py').read()
    # ClientRestart POST diagnostic line with a non-local controller.
    start = len(h.LOG)
    loader._client_restart_post_hook(S(_get_address=lambda: 0x4000), S(NewPawn=pawn), None, None)
    restart_log = [m for _, m in h.LOG[start:]]
    loader._on_disable()
    return dict(repairs=repairs, tps_enabled_after=loader._third_person_enabled,
                stage_registered='("tps_recovery", lambda: tps_recovery.update(owner_module))' in stage_source,
                restart_log=restart_log)


def desync_repair():
    """Settled Default with a stale owner after load: recovery arms, lifecycle repairs."""
    import time
    from types import SimpleNamespace as S
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    from BL4ThirdPersonPOC import tps_recovery
    pushes = []

    class Manager:
        CameraModeState = S(bIsTransitioning=False)
        CameraModeInputs = S(AttachComponent=S(Name='CharacterMesh'))
        mode = 'Default'

        def GetActorCameraMode(self, pawn):
            return self.mode

        def PushActorCameraMode(self, *args):
            pushes.append(args[1:])
            self.mode = 'ThirdPerson'

        def PopActorCameraMode(self, *args):
            pushes.append(('pop',) + args[1:])

        def _get_address(self):
            return 0x2000

    manager = Manager()
    pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: 0x1000)
    pc = S(bShowMouseCursor=False, _get_address=lambda: 0x3000)
    loader._get_runtime = lambda: (pc, pawn, manager)
    loader._is_vehicle_camera_view = lambda: False
    loader._apply_camera_offset = lambda: None
    loader._third_person_enabled = True
    loader._third_person_pushed = True
    loader._camera_stack_owner.update(owned=True, pawn_address=0x1000, manager_address=0x9999)
    results = [tps_recovery.update(loader, now=t) for t in (0.0, 0.5, 0.8)]
    phases = []
    for _ in range(6):
        loader._update_camera_lifecycle()
        phases.append(loader._camera_lifecycle.get('phase'))
        time.sleep(0.08)
    after = tps_recovery.update(loader, now=10.0)
    loader._on_disable()
    return dict(results=results, phases=phases, pushes=[list(map(str, p)) for p in pushes],
                lifecycle_pending=loader._camera_lifecycle.get('pending'), after=after,
                owner=dict(loader._camera_stack_owner),
                log=[m for _, m in h.LOG if 'TPSRecovery' in m or 'CAMERA_LIFECYCLE' in m or 'repair' in m.lower()][-12:])


def respawn_wiring():
    """RespawnCamera without ClientRestart arming reaches respawn_camera.py."""
    from types import SimpleNamespace as S
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    from BL4ThirdPersonPOC import tps_recovery
    manager = S(GetActorCameraMode=lambda pawn: 'RespawnCamera', CameraModeState=S(bIsTransitioning=True),
                CameraModeInputs=S(AttachComponent=S(Name='CharacterMesh')), _get_address=lambda: 0x2000)
    pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: 0x1000)
    pc = S(bShowMouseCursor=False, _get_address=lambda: 0x3000)
    loader._get_runtime = lambda: (pc, pawn, manager)
    loader._is_vehicle_camera_view = lambda: False
    loader._third_person_enabled = True
    armed = tps_recovery.update(loader, now=0.0)
    loader._update_camera_lifecycle()
    respawn_state = loader._respawn_camera_state
    result = dict(armed=armed, lifecycle=dict(reason=loader._camera_lifecycle.get('reason'),
                  pending=loader._camera_lifecycle.get('pending'), phase=loader._camera_lifecycle.get('phase')),
                  respawn_state_created=isinstance(respawn_state, dict),
                  respawn_log=[m for _, m in h.LOG if 'Respawn' in m or 'RESPAWN' in m])
    loader._on_disable()
    return result


def shop_pre_restore():
    """Vending machine use restores owned native state at ServerUseObject PRE (0.3.9.3)."""
    from types import SimpleNamespace as S
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    h.bind_game_thread(loader)
    stops, pops = [], []
    native = dict(active=True)

    class Manager:
        CameraModeState = S(bIsTransitioning=False)
        mode = 'ThirdPerson'

        def GetActorCameraMode(self, pawn):
            return self.mode

        def PopActorCameraMode(self, *args):
            pops.append(args[1])

        def _get_address(self):
            return 0x2000

    manager = Manager()
    pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: 0x1000)
    pc = S(bShowMouseCursor=False, _get_address=lambda: 0x3000)
    loader._get_runtime = lambda: (pc, pawn, manager)
    loader._third_person_enabled = True
    loader._third_person_pushed = True
    loader._camera_stack_owner.update(owned=True, pawn_address=0x1000, manager_address=0x2000)
    loader._native_npc_post_installed = True
    loader._native_active = lambda: native['active']
    loader._cancel_hybrid_ads = lambda reason: None

    def stop(reason):
        stops.append(reason)
        native['active'] = False
        return True

    loader._native_stop = stop

    def usable(cls):
        return S(Class=S(Name=cls), _path_name=lambda: '/Game/Test.' + cls)

    machine = usable('OakVendingMachine')
    loader._server_use_object_redirect_hook(pc, S(Usable=machine), None, None)
    pending_after_use = loader._native_npc_pending
    loader._client_set_current_interactable_hook(pc, S(NewInteractable=machine), None, None)
    manager.mode = 'StructuredInteraction'
    shop_active = loader._shop_camera_active
    # A chest is not a StructuredInteraction usable: no PRE restore.
    native['active'] = True
    loader._server_use_object_redirect_hook(pc, S(Usable=usable('OakChest')), None, None)
    after_chest = list(stops)
    # Quest NPC route keeps its original reason.
    manager.mode = 'ThirdPerson'
    loader._shop_camera_active = False
    loader._third_person_pushed = True
    loader._server_use_object_redirect_hook(pc, S(Usable=usable('OakCharacter')), None, None)
    errors = [m for level, m in h.LOG if level == 'error' and 'NATIVE_PRE' in m]
    loader._on_disable()
    return dict(stops=stops, after_chest=after_chest, pops=pops, shop_active=shop_active,
                pending_after_use=pending_after_use, errors=errors)


def aim_origin_wiring():
    """Enable registers the aim-origin route; console reports; disable removes it."""
    from types import SimpleNamespace as S
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    from BL4ThirdPersonPOC import native_aim_origin, runtime_updates
    from unrealsdk import hooks
    spec = (loader.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, native_aim_origin.ROUTE)
    owner = native_aim_origin.owner()
    registered = runtime_updates.has_hook(*spec)
    start = len(h.LOG)
    loader.aim_origin_console(S(action='margin', value='55'))
    loader.aim_origin_console(S(action='beam_margin', value='30'))
    loader.aim_origin_console(S(action='beam_margin', value='500'))
    loader.aim_origin_console(S(action='off', value=None))
    console = [m for _, m in h.LOG[start:]]
    loader._on_disable()
    return dict(owner=owner is not None, registered=registered, margin=owner.margin, wanted=owner.wanted,
                beam_margin=owner.beam_margin,
                console=console, owner_after=native_aim_origin.owner() is not None,
                errors=[m for level, m in h.LOG if level == 'error' and 'AIM' in m.upper()])


def hybrid_ads_wiring():
    """Option, console tuning and reset of the Hybrid ADS Mode (0.3.9.13)."""
    from types import SimpleNamespace as S
    loader = h.load()
    h.set_build(True)
    h.enable_entry_points(loader)
    loader._on_enable()
    from BL4ThirdPersonPOC import hybrid_ads
    start = len(h.LOG)
    default = loader.omni_hybrid_ads.value
    loader.omni_movement_console(S(action='hybrid', value='on', extra=None))
    enabled = loader.omni_hybrid_ads.value
    loader.omni_movement_console(S(action='hybrid', value='dolly', extra='50'))
    loader.omni_movement_console(S(action='hybrid', value='zoom', extra='1.2'))
    loader.omni_movement_console(S(action='hybrid', value='dolly', extra='500'))
    status = hybrid_ads.status(loader)
    loader.omni_movement_console(S(action='hybrid', value='off', extra=None))
    hybrid_ads._state['scoped'] = True
    loader._on_disable()
    return dict(default=default, enabled=enabled, disabled=loader.omni_hybrid_ads.value,
                has_dolly=('dolly' in status or hasattr(hybrid_ads, 'set_dolly')), zoom=status['zoom_source'], active=status['active'],
                scoped_after_disable=hybrid_ads._state['scoped'],
                registered='omni_hybrid_ads' in [o.identifier for o in loader.mod.options] if hasattr(loader, 'mod') else None,
                console=[m for _, m in h.LOG[start:] if 'HYBRID' in m or 'OMNI_COMMAND_FAILED' in m or 'usage: bl4tps_omni hybrid' in m])


SCENARIOS = {
    'hybrid_ads_wiring': hybrid_ads_wiring,
    'aim_origin_wiring': aim_origin_wiring,
    'shop_pre_restore': shop_pre_restore,
    'respawn_wiring': respawn_wiring,
    'desync_repair': desync_repair,
    'toggle_repair': toggle_repair,
    'from_sdkmod': from_sdkmod,
    'unreviewed': unreviewed,
    'reviewed_omni_on': lambda: reviewed(True),
    'reviewed_omni_off': lambda: reviewed(False),
    'toggle_cycle': toggle_cycle,
}

if __name__ == '__main__':
    try:
        output = dict(ok=True, result=SCENARIOS[sys.argv[1]]())
    except Exception:
        output = dict(ok=False, error=traceback.format_exc(), log=h.LOG[-40:])
    print('RESULT_JSON=' + json.dumps(output, default=str))
