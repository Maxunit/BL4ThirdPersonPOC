"""Own-vehicle exit tickets; paired ClientRestart and live binding admission."""
from . import hitch
from itertools import islice
import math
from time import monotonic
from unrealsdk.unreal import WeakPointer
OMNI_KEY = '_player_omnidirectional_gameplay'
def live(obj):
    obj = None if obj is None else WeakPointer(obj)()
    if obj is None or obj.Class is None: raise RuntimeError('SDK object expired')
    address = int(obj._get_address())
    if not 0x10000 <= address < (1 << 47): raise RuntimeError('SDK address outside user range')
    return obj

def finite(value):
    value = float(value)
    if not math.isfinite(value): raise RuntimeError('Nonfinite diagnostic value')
    return value

class ExitAir:
    def event(self, event, **data):
        if len(self.report['events']) < 128:
            self.report['events'].append(dict(event=event, update=self.frames,
                t=monotonic()-self.started, **data))

    def cancel(self, reason):
        if self.ticket is not None: self.event('EXIT_TICKET_CANCELLED', reason=reason)
        self.ticket = None
        self.binding_wait = None

    def context(self, current=None):
        """Owner/identity guard; current is the runtime resolved earlier in this callback."""
        if (self.updates._owner is not self.producer or not self.producer.active
                or getattr(self.mod, OMNI_KEY, None) is not self.sup or not self.sup.active):
            raise RuntimeError('Omni/update owner changed or stopped')
        pc, pawn, camera = map(live, self.mod._get_runtime() if current is None else current)
        if pc != self.pc_ref() or camera != self.camera_ref():
            raise RuntimeError('Local controller/camera identity changed')
        return pc, pawn, camera

    def permitted(self):
        return self.active and self.updates.is_game_thread()

    def restart(self, stage, obj, args):
        if not self.permitted() or obj != self.pc_ref(): return None
        try:
            pc, pawn, camera = self.context()
            new = getattr(args, 'NewPawn', None)
            if stage == 'PRE':
                self.cancel('NEXT_CLIENT_RESTART')
                self.restart_stack = [(expected, None) for expected, pending in self.restart_stack]
                pending = None
                vehicle = None if self.vehicle_ref is None else self.vehicle_ref()
                if (self.seated and vehicle is not None and new == self.character_ref()
                        and pawn in (vehicle, new) and pc.PersonalVehicleState.Vehicle == vehicle
                        and vehicle.DriverPawn == new):
                    live(new); live(vehicle)
                    pending = dict(character=WeakPointer(new), vehicle=WeakPointer(vehicle),
                                   movement=None, confirmed=False, binding_refs=None)
                    self.event('EXIT_RESTART_PRE', vehicle=hex(int(vehicle._get_address())))
                self.seated = False
                if len(self.restart_stack) >= 8: raise RuntimeError('Nested restart bound exceeded')
                self.restart_stack.append((new, pending))
            else:
                if not self.restart_stack: return None
                expected, pending = self.restart_stack.pop()
                if expected != new: raise RuntimeError('ClientRestart PRE/POST pair differs')
                if (pending is not None and not self.restart_stack and pawn == new
                        and new == pending['character']()):
                    pending['confirmed'] = True
                    self.ticket = pending
                    self.report['confirmed_exits'] += 1
                    self.event('EXIT_RESTART_CONFIRMED')
        except Exception as exc:
            self.fail('restart_' + stage, exc)
        return None

    def allow(self, owner, pc, pawn, camera, movement):
        self.binding_wait = None
        if not self.permitted() or self.ticket is None or not self.ticket['confirmed']: return False
        if owner is not self.sup and not (self.sup.child is owner
                and getattr(owner, 'lifecycle_supervisor', None) is self.sup): return False
        if getattr(owner, 'mod', None) is not self.mod or getattr(owner, 'updates', None) is not self.updates:
            return False
        current = self.context()
        if (current != (pc, pawn, camera) or pawn != self.ticket['character']()
                or pawn != self.character_ref() or movement is None
                or movement != pawn.OakCharacterMovement): return False
        if (not self.mod._third_person_enabled or not self.mod._third_person_pushed
                or pc.bShowMouseCursor or any(bool(getattr(self.mod, name, False)) for name in (
                    '_vehicle_camera_active', '_ads_active', '_shop_camera_active', '_ladder_active', '_slide_active'))
                or camera.CameraModeState.bIsTransitioning or camera.CameraModeInputs.ViewTarget != pawn
                or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson'
                or int(movement.MovementMode) != 3 or int(movement.CustomMovementMode) != 0
                or pawn.IsCharacterDashing() or movement.bWantsToDash
                or any(bool(getattr(movement, name)) for name in (
                    'bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting'))): return False
        if self.ticket['movement'] is None: self.ticket['movement'] = WeakPointer(live(movement))
        if self.ticket['movement']() != movement: return False
        binding = self.ready_binding(pawn, camera)
        if binding is None: return False
        previous = self.ticket['binding_refs']
        if previous is not None and tuple(ref() for ref in previous) != binding:
            # A different weapon/animation/handler must receive the ordinary
            # two stable candidate updates; no new delay or frame counter.
            self.sup.reset_candidate()
        self.ticket['binding_refs'] = tuple(WeakPointer(obj) for obj in binding)
        self.report['allowed_calls'] += 1
        return True

    def wait_reason(self, owner):
        return self.binding_wait if owner is self.sup and self.binding_wait else 'WAITING_GROUNDED'

    def ready_binding(self, pawn, camera):
        def wait(reason):
            self.binding_wait = reason
            if self.report.get('last_binding_wait') != reason:
                self.event('EXIT_BINDING_WAIT', reason=reason)
            self.report['last_binding_wait'] = reason
            counts = self.report.setdefault('binding_wait_counts', {})
            counts[reason] = counts.get(reason, 0) + 1
            return None
        def weak(obj):
            return None if obj is None else WeakPointer(obj)()
        mesh = weak(pawn.Mesh)
        if mesh is None or mesh.Class is None: return wait('WAITING_EXIT_MESH')
        anim = weak(mesh.AnimScriptInstance)
        if anim is None or anim.Class is None: return wait('WAITING_EXIT_ANIMATION')
        weapon = weak(camera.CameraModeInputs.Weapon)
        if weapon is None or weapon.Class is None: return wait('WAITING_EXIT_WEAPON')
        if anim.CurrentWeapon != weapon: return wait('WAITING_EXIT_WEAPON_OWNERSHIP')
        if not all(isinstance(getattr(anim, name), bool) for name in ('bIsFiring', 'bIsReloading')):
            raise RuntimeError('Reviewed animation combat fields differ')
        component = weak(pawn.InputComponent)
        if component is None or component.Class is None: return wait('WAITING_EXIT_INPUT_COMPONENT')
        handlers = tuple(islice(component.BoundActionHandlerList, 17))
        if len(handlers) > 16: raise RuntimeError('Unexpected OnFoot action handler count')
        handlers = [weak(h) for h in handlers if h is not None]
        matches = [h for h in handlers if h is not None and h.Class is not None
                   and str(h.Class.Name) == 'OakEnhancedInputActionHandler_OnFoot']
        if len(matches) != 1: return wait('WAITING_EXIT_ONFOOT_HANDLER')
        binding = tuple(map(live, (mesh, anim, weapon, component, matches[0])))
        self.report['last_binding_wait'] = None
        self.report['ready_binding'] = {name: hex(int(obj._get_address()))
            for name, obj in zip(('mesh','animation','weapon','input_component','onfoot_handler'),binding)}
        return binding

    def air_start(self, child):
        if not self.allow(child, *child.bound()): return
        if not child.active or child.impulse_index is not None:
            raise RuntimeError('New air session activation state differs')
        # Grounded frames normally prepare these lazily. Air facing needs the
        # same reviewed root/Aim/Idle workers and Lean binding before its first
        # callback. Use existing installers with all native/layout guards.
        # Sprint/Dash/vector admission stays with its normal frame pipeline.
        if not child.ready:
            child.native.install()
            child.ready = True
        if child.mesh_ref is None:
            child.bind_visual()
        child.prepare_native()
        node = child.blend_node()
        if child.blend_original is not None:
            raise RuntimeError('Fresh air Lean baseline already captured')
        if not bool(node.bInvertAlpha) or int(node.AlphaInputType) != 1 or bool(node.bAlphaBoolEnabled):
            raise RuntimeError('Reviewed original Lean bool input differs')
        child.blend_original = bool(node.bInvertAlpha)
        # Equivalent private follow bookkeeping to normal movement admission;
        # current body yaw retained. Existing air_frame_observe publishes the
        # ordinary facing controls. No actor/camera/velocity setter here.
        now = monotonic() - child.started
        rotation = child.bound()[1].K2_GetActorRotation()
        child.original_rotation = {k: finite(getattr(rotation, k))
                                   for k in ('Pitch', 'Yaw', 'Roll')}
        child.restore_pending = True
        child.impulse_index = child.frames
        child.follow_started_t = child.follow_previous_t = now
        child.report['block_started_update_index'] = child.frames
        child.report['follow_started_t'] = now
        child.report['vehicle_exit_air'] = True
        self.air_child = child
        self.report['air_rebinds'] += 1
        self.event('AIR_REBOUND', sequence=self.sup.sequence, body_yaw=child.original_rotation['Yaw'])
        self.cancel('CONSUMED_BY_AIR_REBIND')

    def __init__(self, owner):
        self.owner, self.sup, self.mod, self.updates = owner, owner.sup, owner.mod, owner.updates
        self.producer = self.updates._owner
        pc, pawn, camera = map(live, self.mod._get_runtime())
        self.pc_ref, self.character_ref, self.camera_ref = map(WeakPointer, (pc, pawn, camera))
        self.vehicle_ref = self.ticket = self.air_child = self.binding_wait = None
        self.seated = False
        self.restart_stack = []
        self.active = True
        self.frames, self.started = 0, monotonic()
        self.report = dict(events=[], confirmed_exits=0, air_rebinds=0, allowed_calls=0)

    def fail(self, where, exc):
        self.owner.fail(where, exc)

    def frame(self, pc, pawn, camera):
        self.frames += 1
        if not self.owner.normal(pc):
            self.cancel('UI_OR_SPECIAL_OR_TPS_DISABLED')
            self.seated = False
        elif str(pawn.Class.Name) == 'OakVehicle':
            self.cancel('VEHICLE_BOUND')
            if (pc.PersonalVehicleState.Vehicle == pawn and pawn.DriverPawn == self.character_ref()
                    and self.character_ref() is not None):
                self.vehicle_ref, self.seated = WeakPointer(pawn), True
            else: self.seated = False
        elif self.ticket is not None:
            if pawn != self.ticket['character'](): self.cancel('CHARACTER_CHANGED')
            else:
                movement = live(pawn.OakCharacterMovement)
                mode = int(movement.MovementMode)
                if int(movement.CustomMovementMode) != 0 or mode not in (0, 1, 3): self.cancel('SPECIAL_MOVEMENT')
                elif mode == 1: self.cancel('LANDED_BEFORE_AIR_BIND')
                elif pawn.IsCharacterDashing() or movement.bWantsToDash: self.cancel('DASH')

class VehicleHandoff:
    """One supervisor-owned transition worker; all native owners survive cleanup retry."""
    def __init__(self, sup):
        self.sup, self.mod, self.updates = sup, sup.mod, sup.updates
        self.air = self.summon = self.exit = None
        self.active = True
        self.report = dict(exit_rotations=0, errors=[])

    def normal(self, pc):
        return (self.active and self.sup.active and self.mod._third_person_enabled and not pc.bShowMouseCursor
                and not any(bool(getattr(self.mod, name, False)) for name in
                    ('_ads_active', '_shop_camera_active', '_ladder_active', '_slide_active')))

    def arm(self):
        from .vehicle_exit import ExitFacing
        from .vehicle_summon import SummonFacing
        # Assign before publication so any partial failure remains recoverable.
        self.air = ExitAir(self)
        self.exit = ExitFacing.__new__(ExitFacing)
        self.exit.__init__(self)
        self.exit.install()
        drive = bool(getattr(getattr(self.mod, 'vehicle_camera_relative_drive', None), 'value', False))
        if drive:
            self.summon = SummonFacing.__new__(SummonFacing)
            self.summon.__init__(self)
            self.summon.install()

    def disarm(self):
        for worker in (self.summon, self.exit):
            if worker is not None and hasattr(worker, 'control'): worker.disarm()

    def patch_count(self):
        summon = len(getattr(self.summon, 'native_hooks', {}))
        exit_count = sum(getattr(self.exit, name, None) is not None for name in ('hook', 'gap_hook'))
        return summon + exit_count

    def frame(self):
        if not self.active or not self.updates.is_game_thread():
            self.disarm()
            return
        pc, pawn, camera = self.mod._get_runtime()
        if any(obj is None for obj in (pc, pawn, camera)):
            self.disarm()
            if self.air is not None: self.air.cancel('RUNTIME_UNAVAILABLE')
            return
        child = self.sup.child
        if self.air is None:
            if child is None or not child.active or str(pawn.Class.Name) != 'OakCharacter': return
            with hitch.step('vehicle.arm'):
                self.arm()
        elif (pc != self.air.pc_ref() or camera != self.air.camera_ref()
                or self.air.character_ref() is None
                or (str(pawn.Class.Name) == 'OakCharacter' and pawn != self.air.character_ref())):
            with hitch.step('vehicle.stop'):
                self.stop()
            self.sup.vehicle = None
            return
        if not self.normal(pc):
            self.disarm()
            self.air.cancel('SPECIAL_OR_DISABLED')
            self.air.seated = False
            return
        # Same callback, same game thread: reuse the runtime resolved above.
        self.air.context((pc, pawn, camera))
        drive = bool(getattr(getattr(self.mod, 'vehicle_camera_relative_drive', None), 'value', False))
        if self.summon is not None and not drive:
            self.summon.stop()
            self.summon = None
        elif self.summon is None and drive and pawn == self.air.character_ref() and child is not None and child.active:
            from .vehicle_summon import SummonFacing
            self.summon = SummonFacing.__new__(SummonFacing)
            self.summon.__init__(self)
            self.summon.install()
        with hitch.step('vehicle.exit_air'):
            self.air.frame(pc, pawn, camera)
        if self.summon is not None:
            with hitch.step('vehicle.summon'):
                self.summon.frame(pc, pawn, camera)
        with hitch.step('vehicle.exit_facing'):
            self.exit.frame(pc, pawn, camera)

    def restart(self, stage, obj, args):
        if self.air is None: return
        if stage == 'PRE':
            # Stop minting summon tickets during possession changes. The exit
            # gap was published before the native launch and must remain armed.
            if self.summon is not None: self.summon.control[0] = 0
        self.air.restart(stage, obj, args)

    def early_drive(self, child, pc, pawn, camera):
        s = self.summon
        if (not self.active or s is None or not s.active or not self.updates.is_game_thread()
                or not s.control[9] or not s.control[16] or not s.control[13]
                or not bool(self.mod.vehicle_camera_relative_drive.value)):
            return False
        from .vehicle_summon import live as pointer
        drive = s.drive_owner
        if (drive is None or not drive.active or getattr(s.drive_module, '_owner', None) is not drive
                or drive.child is not child): return False
        starting = (getattr(drive, '_starting', False) and not child.native_hooks
                    and getattr(child, 'buffer', None) is None)
        if not child.active and not starting:
            return False
        if self.updates._owner is not s.producer or not s.producer.active:
            return False
        pc, pa = pointer(pc)
        pawn, va = pointer(pawn)
        camera, ca = pointer(camera)
        if (pc != s.pc_ref() or pa != s.pc_address or pc.bShowMouseCursor
                or str(pawn.Class.Name) != 'OakVehicle' or va != s.control[17]
                or str(camera.Class.Name) != 'OakPlayerCameraManager'
                or pc.PersonalVehicleState.Vehicle != pawn): return False
        if s.u64(pa+0x39A8) != va or s.u64(pa+0x3D0) != va: return False
        s.field(pawn.Class, 'OakVehicleMovement', 'ObjectProperty', 0x1700, 8)
        movement, ma = pointer(pawn.OakVehicleMovement)
        if (str(movement.Class._path_name()) != '/Script/OakGame.OakWheeledVehicleMovementComponent'
                or s.u64(va) != s.base+0xB8D0A80 or s.u64(ma) != s.base+0xB8F37E0
                or s.u64(va+0x1700) != ma): return False
        if child.native_hooks:
            if len(child.native_hooks) != 1 or child.native_hooks[0]['target'] != s.base+0xBDA5BD:
                raise RuntimeError('Early drive owned hook differs')
            for hook in child.native_hooks: s.chain.verify(self.mod, hook)
        # A first-ever Capture has no yaw hook yet; its ordinary install proves
        # the executable, reflected offsets, vtable and original site before write.
        return True

    def fail(self, where, exc):
        self.disarm()
        self.report['errors'].append(dict(where=where, error=repr(exc)[:300]))
        self.sup.fail('vehicle_' + where, exc)

    def stop(self):
        self.active = False
        self.disarm()
        if self.air is not None:
            self.air.active = False
            self.air.cancel('STOPPED')
        failures = []
        for worker in (self.summon, self.exit):
            if worker is not None:
                try: worker.stop()
                except Exception as exc: failures.append(repr(exc))
        if failures: raise RuntimeError('Vehicle cleanup incomplete: ' + '; '.join(failures))

def allow_early_drive(child, pc, pawn, camera):
    sup = getattr(child.mod, '_player_omnidirectional_gameplay', None)
    vehicle = getattr(sup, 'vehicle', None)
    return vehicle is not None and vehicle.early_drive(child, pc, pawn, camera)

def allow_exit_air(owner, pc, pawn, camera, movement):
    sup = owner if hasattr(owner, 'child') else getattr(owner, 'lifecycle_supervisor', None)
    vehicle = getattr(sup, 'vehicle', None)
    return (vehicle is not None and vehicle.active and vehicle.air is not None
            and vehicle.air.allow(owner, pc, pawn, camera, movement))
