"""Keep hidden loader keybinds on the keys the player configured in the game.

mods_base keybinds fire on one physical key. Enhanced Input lets the player
remap actions, so a fixed RightMouseButton/Gamepad_LeftTrigger bind misses a
remapped ADS. This owner reads the effective mappings of a confirmed action
asset and moves each keybind to the configured key of its device class.

Rules:
- Only confirmed action assets are followed (ROLE_ACTIONS). A role without a
  confirmed asset keeps its shipped key; nothing is guessed.
- Without a usable configured key the keybind keeps its current key.
- The current key is kept while it is still one of the configured keys.
- Analog trigger axes map to their digital trigger key (press/release events).
- Work runs on the owned game-thread widget tick, skips open menus, and does a
  full scan only on a mapping-count change, a menu close or a fixed cadence.
"""
from unrealsdk import hooks
from unrealsdk.unreal import WeakPointer

from . import runtime_updates
from .input_bindings import (
    ACTION_ROOT,
    action_asset,
    configured_key_names,
    validate_mapping_schema,
)

KEY = 'bl4tps.action_keys'
TAG = '[BL4ThirdPersonPOC.ActionKeys]'
SYNC_INTERVAL_UPDATES = 120

# Role -> confirmed Enhanced Input action asset below ACTION_ROOT.
# Action_Zoom is the ADS action read successfully in the omni mapping tests.
# Action_Use was confirmed in game on 2026-10-08 (`bl4tps_actions all` in front
# of a vending machine: E, Gamepad_FaceButton_Left). Its rows exist only while
# the interaction context is applied, so away from interactables the keybind
# keeps its current key (KEPT_NO_CONFIGURED_KEY) and follows on the next
# mapping-count change.
ROLE_ACTIONS = {
    'ads': 'Action_Zoom',
    'interact': 'Action_Use',
}

AXIS_TO_DIGITAL = {
    'Gamepad_LeftTriggerAxis': 'Gamepad_LeftTrigger',
    'Gamepad_RightTriggerAxis': 'Gamepad_RightTrigger',
}
# Keys without press/release events cannot drive an event keybind.
ANALOG_ONLY = {
    'MouseX', 'MouseY', 'Mouse2D', 'MouseWheelAxis',
    'Gamepad_LeftX', 'Gamepad_LeftY', 'Gamepad_RightX', 'Gamepad_RightY',
    'Gamepad_Left2D', 'Gamepad_Right2D',
}


def device_of(name):
    return 'gamepad' if name.startswith('Gamepad_') else 'kbm'


def usable_keys(names, device):
    """Configured key names usable by an event keybind of one device class."""
    result = []
    for name in names:
        name = AXIS_TO_DIGITAL.get(name, name)
        if name in ANALOG_ONLY or device_of(name) != device or name in result:
            continue
        result.append(name)
    return result


def choose_key(current, names, device):
    """Keep the current key while configured; else the first configured key; else None."""
    candidates = usable_keys(names, device)
    if not candidates:
        return None
    return current if current in candidates else candidates[0]


class Owner:
    def __init__(self, mod, bindings):
        self.mod = mod
        # bindings: tuple of (role, device, keybind)
        self.bindings = tuple(bindings)
        self.spec = (mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, KEY + '.frame')
        self.registered = False
        self.active = False
        self.busy = False
        self.updates_since_sync = SYNC_INTERVAL_UPDATES
        self.mapping_count = None
        self.menu_open = False
        self.schema_owner = None
        self.state = {}
        self.sync_count = 0
        self.last_error = None
        # Diagnostics for `bl4tps_actions`: routed frames and early exits.
        self.frames = 0
        self.skips = {}
        self.route_restores = 0

    def skip(self, reason):
        self.skips[reason] = self.skips.get(reason, 0) + 1

    def route_registered(self):
        return self.registered and runtime_updates.has_hook(*self.spec)

    def ensure_route(self):
        """Re-add a lost widget route while the owner is active (console self-check)."""
        if not self.active or not self.registered or runtime_updates.has_hook(*self.spec):
            return False
        runtime_updates.add_hook(*self.spec, self.frame)
        if not runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Action key route restore unverified')
        self.route_restores += 1
        self.mod.logging.warning(TAG + ' ROUTE_RESTORED widget route was missing')
        return True

    def install(self):
        if runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Action key sync already registered')
        self.registered = True
        runtime_updates.add_hook(*self.spec, self.frame)
        if not runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Action key sync registration unverified')
        self.active = True

    def frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        if not runtime_updates.is_game_thread():
            self.skip('not_game_thread')
            return
        self.busy = True
        self.frames += 1
        try:
            pc = self.mod._get_runtime()[0]
            if pc is None:
                self.skip('no_controller')
                return
            if bool(pc.bShowMouseCursor):
                # Remapping happens in menus; sync once they close.
                self.menu_open = True
                self.skip('cursor_shown')
                return
            player_input = getattr(pc, 'PlayerInput', None)
            if player_input is None:
                self.skip('no_player_input')
                return
            count = len(player_input.EnhancedActionMappings)
            self.updates_since_sync += 1
            if (not self.menu_open and count == self.mapping_count
                    and self.updates_since_sync < SYNC_INTERVAL_UPDATES):
                return
            self.menu_open = False
            self.sync(player_input)
            self.mapping_count = count
        except Exception as exc:
            # Keep the current keys; report once per distinct error.
            text = repr(exc)[:300]
            if text != self.last_error:
                self.last_error = text
                self.mod.logging.error(TAG + ' SYNC_FAILED keys unchanged: ' + text)
        finally:
            self.busy = False

    def sync(self, player_input):
        self.updates_since_sync = 0
        owner = None if self.schema_owner is None else self.schema_owner()
        if owner is None or owner != player_input:
            validate_mapping_schema(player_input)
            self.schema_owner = WeakPointer(player_input)
        self.sync_count += 1
        for role, device, keybind in self.bindings:
            asset = ROLE_ACTIONS.get(role)
            if asset is None:
                self.state[(role, device)] = dict(asset=None, key=keybind.key, status='UNCONFIRMED_ACTION')
                continue
            names = configured_key_names(player_input, asset)
            chosen = choose_key(keybind.key, names, device)
            if chosen is None:
                self.state[(role, device)] = dict(asset=asset, key=keybind.key, configured=names, status='KEPT_NO_CONFIGURED_KEY')
                continue
            if chosen != keybind.key:
                previous = keybind.key
                keybind.key = chosen
                self.mod.logging.info(TAG + ' REBOUND role=' + role + ' device=' + device
                                      + ' ' + str(previous) + ' -> ' + chosen)
            self.state[(role, device)] = dict(asset=asset, key=keybind.key, configured=names, status='FOLLOWING')

    def close(self):
        self.active = False
        if self.registered:
            if runtime_updates.has_hook(*self.spec):
                runtime_updates.remove_hook(*self.spec)
            if runtime_updates.has_hook(*self.spec):
                return False
            self.registered = False
        return True


_owner = None


def start(mod, bindings):
    global _owner
    if not shutdown():
        raise RuntimeError('Action key sync cleanup incomplete')
    _owner = Owner(mod, bindings)
    try:
        _owner.install()
    except Exception:
        shutdown()
        raise


def shutdown():
    global _owner
    if _owner is None:
        return True
    if not _owner.close():
        return False
    _owner = None
    return True


def report():
    if _owner is None:
        return dict(running=False)
    return dict(running=_owner.active, syncs=_owner.sync_count, last_error=_owner.last_error,
                frames=_owner.frames, skips=dict(_owner.skips),
                route_registered=_owner.route_registered(), route_restores=_owner.route_restores,
                bindings={role + '/' + device: value for (role, device), value in _owner.state.items()})


def sync_now(player_input):
    """Console path: restore a lost route and sync immediately on the game thread.

    Returns the reason when nothing was synced. The console command runs on the
    game thread; the runtime_updates thread identity is still required.
    """
    if _owner is None or not _owner.active:
        return 'not_running'
    if not runtime_updates.is_game_thread():
        return 'not_game_thread'
    if _owner.busy:
        return 'busy'
    _owner.ensure_route()
    _owner.busy = True
    try:
        _owner.sync(player_input)
        _owner.mapping_count = len(player_input.EnhancedActionMappings)
        _owner.menu_open = False
    finally:
        _owner.busy = False
    return None


def list_actions(player_input):
    """All action assets below ACTION_ROOT with their configured keys (console diagnostic)."""
    validate_mapping_schema(player_input)
    actions = {}
    for row in player_input.EnhancedActionMappings:
        asset = action_asset(row.Action)
        if asset is None:
            continue
        name = str(row.Key.KeyName)
        entry = actions.setdefault(asset, [])
        label = name + (' (ignored)' if bool(row.bShouldBeIgnored) else '')
        if label not in entry:
            entry.append(label)
    return dict(root=ACTION_ROOT, actions=dict(sorted(actions.items())))


def list_all_mappings(player_input):
    """Every effective mapping row, including actions outside ACTION_ROOT.

    0.3.9.0 showed no Use/Interact action below ACTION_ROOT and no row for E,
    so the interaction action lives elsewhere or in a context that is only
    applied near an interactable. Read-only; full object paths are reported.
    """
    validate_mapping_schema(player_input)
    rows = {}
    for row in player_input.EnhancedActionMappings:
        action = row.Action
        path = '<none>' if action is None else str(action._path_name())
        name = str(row.Key.KeyName)
        entry = rows.setdefault(path, [])
        label = name + (' (ignored)' if bool(row.bShouldBeIgnored) else '')
        if label not in entry:
            entry.append(label)
    return dict(count=len(player_input.EnhancedActionMappings), actions=dict(sorted(rows.items())))
