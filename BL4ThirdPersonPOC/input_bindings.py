"""Read the local player's effective Enhanced Input mappings, without key defaults.

This adapter observes configured-key intent. It does not emulate Enhanced Input
triggers or declare that an action was admitted. Movement uses the pawn's native
movement vector; Sprint/Dash dispatch and resources stay in the native callbacks.

Shared by the omnidirectional feature (role snapshots) and the loader's action
key synchronisation (ADS/interaction keybinds follow the configured game keys).

Cost control: a full mapping scan reads every row through the SDK. Callers that
run per frame use ``maybe_refresh`` (count change, forced edge, or a bounded
update cadence) and ``begin_frame`` so one callback evaluates key state once.
"""
import math
from copy import copy
from unrealsdk.unreal import WeakPointer

# Semantic action assets observed in the SDK inventory. These are actions,
# never physical keyboard/controller bindings or an alternative default layout.
ACTION_ROLES = {
    'Action_Sprint': 'sprint',
    'Action_Dash': 'dash',
    'Action_Crouch': 'crouch',
    'Action_Crouch_Hold': 'crouch',
    'Action_Jump_HoldToGlide': 'jump',
    'Action_Fire': 'fire',
    'Action_Zoom': 'zoom',
    # Ordnance (grenade/heavy weapon) key; omni treats it as throw intent.
    'Action_Gadget': 'gadget',
    # Measured in the .15 carry/throw observer (RMB/LT in the tested bindings).
    'Action_Carry_Throw': 'carry_throw',
}
ACTION_ROOT = '/Game/GameData/Input/EnhancedInput/'
ROLES = ('sprint', 'dash', 'crouch', 'jump', 'fire', 'zoom', 'gadget', 'carry_throw')
# Throwable contexts legitimately omit Action_Zoom. Absence means no zoom
# intent; never retain a stale binding or substitute a physical key.
OPTIONAL_ROLES = ('zoom', 'gadget', 'carry_throw')
REQUIRED_ROLES = tuple(role for role in ROLES if role not in OPTIONAL_ROLES)
# Roles whose unusable mappings (foreign action class, missing key, Chord/Combo
# triggers this adapter cannot evaluate) are skipped as "no intent" instead of
# refused. Movement, Fire and Zoom keep the fail-closed refusal.
SKIPPABLE_ROLES = ('gadget', 'carry_throw')
MAX_MAPPINGS = 512
# Update cadence for the full scan when nothing else forces it. Counted in
# owned updates, not elapsed time. Mapping-count changes refresh immediately.
REFRESH_INTERVAL_UPDATES = 30


def reflected_fields(cls):
    return {str(p.Name): p for owner in (cls, *tuple(cls._superfields()))
            for p in owner._properties()}


def validate_mapping_schema(player_input):
    """Verify the reflected EnhancedActionMappings layout this adapter reads."""
    if str(player_input.Class._path_name()) != '/Script/GbxEnhancedInput.GbxEnhancedPlayerInput':
        raise RuntimeError('Enhanced PlayerInput class differs; no key fallback')
    fields = reflected_fields(player_input.Class)
    mapping = fields.get('EnhancedActionMappings')
    if (mapping is None or str(mapping.Class.Name) != 'ArrayProperty'
            or int(mapping.Offset_Internal) != 1344):
        raise RuntimeError('EnhancedActionMappings schema differs')
    inner = mapping.Inner
    if (str(inner.Class.Name) != 'StructProperty'
            or str(inner.Struct.Name) != 'EnhancedActionKeyMapping'):
        raise RuntimeError('Enhanced action mapping element schema differs')
    layout = reflected_fields(inner.Struct)
    expected = {'Action': ('ObjectProperty', 32), 'Key': ('StructProperty', 40),
                'bShouldBeIgnored': ('BoolProperty', 64), 'Triggers': ('ArrayProperty', 0)}
    for name, specification in expected.items():
        prop = layout.get(name)
        if prop is None or (str(prop.Class.Name), int(prop.Offset_Internal)) != specification:
            raise RuntimeError('Enhanced mapping field differs: ' + name)
    key = layout['Key']
    if str(key.Struct._path_name()) != '/Script/InputCore.Key':
        raise RuntimeError('Enhanced mapping Key struct differs')


def action_asset(action):
    """Return the asset name of an action below ACTION_ROOT, or None."""
    if action is None:
        return None
    path = str(action._path_name())
    if not path.startswith(ACTION_ROOT):
        return None
    relative = path[len(ACTION_ROOT):]
    if '.' not in relative:
        return None
    asset, object_name = relative.split('.', 1)
    if object_name != asset:
        return None
    return asset


def configured_key_names(player_input, asset):
    """Return the non-ignored key names currently mapped to one action asset."""
    names = []
    for row in player_input.EnhancedActionMappings:
        if action_asset(row.Action) != asset:
            continue
        name = str(row.Key.KeyName)
        if name and name != 'None' and not bool(row.bShouldBeIgnored) and name not in names:
            names.append(name)
    return names


class NativeBindings:
    def __init__(self, controller):
        player_input = getattr(controller, 'PlayerInput', None)
        if player_input is None:
            raise RuntimeError('Local Enhanced PlayerInput unavailable; no key fallback')
        for method in ('IsInputKeyDown', 'GetInputAnalogKeyState'):
            if not callable(getattr(controller, method, None)):
                raise RuntimeError('Configured input getter unavailable: ' + method)
        validate_mapping_schema(player_input)
        self.controller_ref = WeakPointer(controller)
        self.player_input_ref = WeakPointer(player_input)
        self.bindings = {role: [] for role in ROLES}
        self.present_roles = frozenset()
        self.skipped_optional = 0
        self.mapping_count = None
        self.revision = 0
        self.signature = None
        self.complete = False
        self.updates_since_refresh = 0
        self.refresh_count = 0
        # Per-callback snapshot cache; disabled until begin_frame() is used.
        self.frame_cache_enabled = False
        self.frame_snapshot = None

    def matches(self, controller):
        pc, player_input = self.controller_ref(), self.player_input_ref()
        return pc is not None and player_input is not None and pc == controller and pc.PlayerInput == player_input

    def begin_frame(self):
        """Start one owned callback: key state is evaluated at most once until the next call."""
        self.frame_cache_enabled = True
        self.frame_snapshot = None

    def maybe_refresh(self, require_complete=False, force=False):
        """Bounded per-update refresh with the same fail-closed owner/completeness rules."""
        pc, player_input = self.controller_ref(), self.player_input_ref()
        if pc is None or player_input is None or pc.PlayerInput != player_input:
            raise RuntimeError('Configured input owner changed; explicit rebind required')
        self.updates_since_refresh += 1
        if (force or self.mapping_count is None
                or len(player_input.EnhancedActionMappings) != self.mapping_count
                or self.updates_since_refresh >= REFRESH_INTERVAL_UPDATES
                or (require_complete and not self.complete)):
            return self.refresh(require_complete=require_complete)
        return self.complete

    def refresh(self, require_complete=False):
        pc, player_input = self.controller_ref(), self.player_input_ref()
        if pc is None or player_input is None or pc.PlayerInput != player_input:
            raise RuntimeError('Configured input owner changed; explicit rebind required')
        mappings = player_input.EnhancedActionMappings
        if not 0 <= len(mappings) <= MAX_MAPPINGS:
            raise RuntimeError('Enhanced action mapping count outside bound')
        bindings = {role: [] for role in ROLES}
        seen_roles = set()
        skipped_optional = 0
        signature = []
        for row in mappings:
            action = row.Action
            if action is None:
                continue
            path = str(action._path_name())
            if not path.startswith(ACTION_ROOT):
                continue
            relative = path[len(ACTION_ROOT):]
            if '.' not in relative:
                continue
            asset, object_name = relative.split('.', 1)
            role = ACTION_ROLES.get(asset)
            if role is None or object_name != asset:
                continue
            if str(action.Class._path_name()) != '/Script/GbxEnhancedInput.GbxEnhancedInputAction':
                if role in SKIPPABLE_ROLES:
                    skipped_optional += 1
                    continue
                raise RuntimeError('Configured action class differs: ' + asset)
            key = row.Key
            name = str(key.KeyName)
            if not name or name == 'None':
                if role in SKIPPABLE_ROLES:
                    skipped_optional += 1
                    continue
                raise RuntimeError('Configured action key missing: ' + asset)
            ignored = bool(row.bShouldBeIgnored)
            triggers = tuple(row.Triggers) + tuple(action.Triggers)
            complex_trigger = any(
                trigger is not None and any(word in str(trigger.Class.Name) for word in ('Chord', 'Combo'))
                for trigger in triggers)
            if complex_trigger:
                if role not in SKIPPABLE_ROLES:
                    raise RuntimeError('Complex configured action trigger requires native value support: ' + asset)
                skipped_optional += 1
                continue
            # WrappedStruct is a borrowed view into a mutable engine array.
            # Only keep SDK-owned copies across callbacks. copy.copy() preserves
            # the reflected current KeyName; no physical key is substituted.
            # Every refresh replaces these snapshots, including changes with the
            # same mapping count. Ignored mappings prove presence, not intent.
            seen_roles.add(role)
            signature.append((role, int(action._get_address()), name, ignored))
            if not ignored:
                owned_key = copy(key)
                if owned_key is key or str(owned_key.KeyName) != name:
                    raise RuntimeError('Configured key copy differs: ' + asset)
                bindings[role].append(owned_key)
        complete = all(role in seen_roles for role in REQUIRED_ROLES)
        if require_complete and not complete:
            missing = ', '.join(role for role in REQUIRED_ROLES if role not in seen_roles)
            raise RuntimeError('Current gameplay action mappings missing: ' + missing + '; no defaults')
        frozen = tuple(sorted(signature))
        if frozen != self.signature:
            self.signature = frozen
            self.revision += 1
        self.bindings = bindings
        self.present_roles = frozenset(seen_roles)
        self.skipped_optional = skipped_optional
        self.mapping_count = len(mappings)
        self.complete = complete
        self.updates_since_refresh = 0
        self.refresh_count += 1
        self.frame_snapshot = None
        return complete

    def snapshot(self, controller):
        if not self.matches(controller):
            raise RuntimeError('Configured input snapshot owner changed')
        if self.mapping_count != len(self.player_input_ref().EnhancedActionMappings):
            self.refresh()
        if self.frame_cache_enabled and self.frame_snapshot is not None:
            return dict(self.frame_snapshot)
        result = {}
        for role, keys in self.bindings.items():
            active = False
            for key in keys:
                digital = bool(controller.IsInputKeyDown(key))
                analog = float(controller.GetInputAnalogKeyState(key))
                if not math.isfinite(analog):
                    raise RuntimeError('Nonfinite configured action value: ' + role)
                active = active or digital or abs(analog) > 0.05
            result[role] = active
        if self.frame_cache_enabled:
            self.frame_snapshot = dict(result)
        return result

    def metadata(self):
        return {'source': 'local PlayerInput.EnhancedActionMappings',
                'revision': self.revision, 'mapping_count': self.mapping_count,
                'complete': self.complete, 'full_refreshes': self.refresh_count,
                'present_roles': sorted(self.present_roles),
                'skipped_optional_mappings': self.skipped_optional,
                'key_storage': 'SDK-owned copies of current mapped FKeys',
                'bound_keys': {role: [str(key.KeyName) for key in keys]
                               for role, keys in self.bindings.items()},
                'semantics': 'configured-key intent; native callbacks decide admission'}


