"""Deterministic SDK cost count of idle Omni updates (lifecycle PRE + gameplay POST).

Runs the real Omni pipeline against a fake BL4 world in which every reflected
property read, UFunction call, WeakPointer deref, ReadProcessMemory and thread
check is counted and attributed to the innermost pipeline stage. Counts are
exact for this fake world; they are not timings and not FPS. The vehicle POST
callback is not included.

Usage: python omni_idle_cost_scenario.py [stand|crouch|move|turn] [--report]
move: running straight at 400 cm/s; turn: running while the camera turns 90 deg/s.
Assumptions: 2 configured keys per role, 120 mapping rows, 8 instanced scripts.
"""
import struct
import sys
import types
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace as S

import json

REPO = Path(__file__).resolve().parents[1]
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
SCENARIO = ARGS[0] if ARGS else 'stand'
REPORT = '--report' in sys.argv
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))

# ----------------------------------------------------------------- counters
COUNTS = defaultdict(Counter)       # stage -> category -> n
DETAIL = defaultdict(Counter)       # category -> name -> n
STACK = ['<outside>']
CALLS = Counter()
ENABLED = [False]


def hit(category, name=''):
    if not ENABLED[0]:
        return
    COUNTS[STACK[-1]][category] += 1
    if name:
        DETAIL[category][name] += 1


# ------------------------------------------------------------ SDK stand-ins
import support  # noqa: E402  (creates unrealsdk stub modules)


class WP:
    __slots__ = ('o',)

    def __init__(self, obj):
        hit('weak_new')
        self.o = obj

    def __call__(self):
        hit('weak_deref')
        return self.o


sys.modules['unrealsdk.unreal'].WeakPointer = WP

# KismetInputLibrary: index 0 keys = keyboard/mouse buttons, index 1 = gamepad;
# gamepad Fire/Zoom use trigger button-axis keys (kept on both reads).
def _is_button_axis(key):
    hit('ufunc', 'KismetInputLibrary.Key_IsButtonAxis')
    name = str(key.KeyName)
    return name in ('Action_Fire1', 'Action_Zoom1')


def _is_analog(key):
    hit('ufunc', 'KismetInputLibrary.Key_IsAnalog')
    return False


_input_library = S(Key_IsButtonAxis=_is_button_axis, Key_IsAnalog=_is_analog)
OFFHAND_PATH = '/Game/PlayerCharacters/_Shared/Tricks/Skills/Script_LTrick_HandleOffhand.Script_LTrick_HandleOffhand_C'
_classes = {}


def _find_class(name):
    if name == '/Script/Engine.KismetInputLibrary':
        return S(ClassDefaultObject=_input_library)
    if name == OFFHAND_PATH:
        if name not in _classes:
            _classes[name] = Fake('OffhandScriptClass', addr=0x5C1, path=OFFHAND_PATH)
        return _classes[name]
    raise ValueError('not loaded: ' + name)


sys.modules['unrealsdk'].find_class = _find_class


class Fake:
    """Reflected UObject/WrappedStruct: every field access is one SDK getattr."""

    def __init__(self, name, cls=None, props=None, funcs=None, addr=0, path=None):
        object.__setattr__(self, '_n', name)
        object.__setattr__(self, '_d', dict(props or {}))
        object.__setattr__(self, '_f', dict(funcs or {}))
        object.__setattr__(self, '_a', addr)
        object.__setattr__(self, '_p', path or ('/Game/' + name))
        if cls is not None:
            self._d['Class'] = cls

    def __getattr__(self, key):
        d = object.__getattribute__(self, '_d')
        if key in d:
            hit('prop_get', object.__getattribute__(self, '_n') + '.' + key)
            return d[key]
        f = object.__getattribute__(self, '_f')
        if key in f:
            impl = f[key]
            label = object.__getattribute__(self, '_n') + '.' + key

            def call(*args, **kwargs):
                hit('ufunc', label)
                return impl(*args, **kwargs)
            return call
        raise AttributeError(key)

    def __setattr__(self, key, value):
        hit('prop_set', self._n + '.' + key)
        self._d[key] = value

    def _get_address(self):
        hit('addr')
        return self._a

    def _path_name(self):
        hit('path_name')
        return self._p

    def __eq__(self, other):
        hit('uobj_eq')
        return self is other

    def __ne__(self, other):
        hit('uobj_eq')
        return self is not other

    __hash__ = object.__hash__

    def __repr__(self):
        return 'Fake(' + self._n + ')'


class Enum:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


def cls(name, path=None):
    return Fake(name + 'Class', props=dict(Name=name), path=path or '/Script/X.' + name)


def rot(yaw=10.0):
    return Fake('Rotator', props=dict(Pitch=0.0, Yaw=yaw, Roll=0.0))


def vec(x=0.0, y=0.0, z=0.0):
    return Fake('Vector', props=dict(X=x, Y=y, Z=z))


# ---------------------------------------------------------------- the world
BASE = 0x140000000
mem = {}


def native_read(address, size):
    hit('rpm', hex(address))
    data = mem.get(address)
    if data is None:
        data = bytes(size)
    return data[:size].ljust(size, b'\0')


def native_query(address):
    hit('virtual_query')
    return S(BaseAddress=address & ~0xFFF, State=0x1000, Protect=4, Type=0x20000, RegionSize=0x10000)


kernel32 = S(GetCurrentThreadId=lambda: (hit('thread_check'), 7)[1],
             GetModuleHandleW=lambda _: BASE, GetCurrentProcess=lambda: -1)

import math  # noqa: E402
MOTION = dict(t=0.0, yaw=0.0, velocity_yaw=0.0, speed=0.0)


def actor_rotation():
    return rot(MOTION['yaw'])


def set_actor_rotation(rotator, sweep=False):
    MOTION['yaw'] = float(rotator.Yaw)
    return True


def motion_vector(scale):
    radians = math.radians(MOTION['velocity_yaw'])
    return vec(math.cos(radians) * scale, math.sin(radians) * scale, 0.0)


weapon = Fake('Weapon', cls('OakWeapon'), dict(CurrentState=Enum('Active')), addr=0x9000)
TAG = lambda text: Fake('Tag', props=dict(TagName=text))  # noqa: E731


def anim_node(**extra):
    props = dict(ALPHA=1.0, BlendWeight=1.0, AlphaInputType=1, bAlphaBoolEnabled=False,
                 bInvertAlpha=False, RotationChannelName=TAG('RotationChannel.Aim'),
                 BlendSpaceKey=TAG('AnimSet.Player.3rd.AimO_3rd'),
                 AlphaBoolBlend=Fake('Blend', props=dict(BlendInTime=0.1, BlendOutTime=0.1)))
    props.update(extra)
    return Fake('AnimNode', props=props)


ANIM_ADDR = 0x50000000
from BL4ThirdPersonPOC.omni.session import GameplaySession  # noqa: E402
anim_props = {n: (False if n.startswith('b') else 0.0) for n in GameplaySession.INPUT_NAMES}
anim_props.update(bIsFiring=False, bIsReloading=False, bIsCarrying=False, CurrentWeapon=weapon,
                  AimYaw=0.0, AimPitch=0.0)
anim_props[GameplaySession.NODE_NAME] = anim_node()
anim_props[GameplaySession.BLEND_NODE] = anim_node()
players = [Fake('Player', props=dict(BlendWeight=1.0, InternalTimeAccumulator=0.0, BlendSpace=None)) for _ in range(2)]
anim_props['GbxAnimGraphNode_Locomotion_2'] = Fake('Loco', props=dict(BlendSpacePlayers=players))
forward_clip = Fake('Dash_F', cls('AnimSequence'), addr=0xA000)
for node_name, key in GameplaySession.DASH_PLAYERS:
    anim_props[node_name] = Fake('DashPlayer', props=dict(
        AnimAssetKey=TAG(key), Sequence=Fake(key, cls('AnimSequence'), addr=0xA100 + len(anim_props)),
        BlendWeight=0.0, InternalTimeAccumulator=0.0))
anim = Fake('AnimInstance', cls('BPAnim_Player_3rd_C'), anim_props,
            funcs=dict(GetCurrentActiveMontage=lambda: None,
                       GetAnimationFromTag=lambda key: forward_clip), addr=ANIM_ADDR)
mesh = Fake('Mesh', props=dict(AnimScriptInstance=anim, RelativeRotation=rot()), addr=0x51000000)
MOVE_ADDR = 0x60000000
component_obj = Fake('CapsuleComponent', addr=0x61000000)
movement = Fake('Movement', cls('OakCharacterMovementComponent'), dict(
    MovementMode=1, CustomMovementMode=0, bWantsToDash=False, bWantsToSprint=False,
    bWantsToStartSprinting=False, bIsSprinting=False, Velocity=vec(), Acceleration=vec(),
    bOrientRotationToMovement=False, bUseControllerDesiredRotation=False, LastDashTime=0.0,
    UpdatedComponent=component_obj), addr=MOVE_ADDR)
handler = Fake('OnFootHandler', cls('OakEnhancedInputActionHandler_OnFoot'), addr=0x62000000)
input_component = Fake('InputComponent', props=dict(
    BoundActionHandlerList=[Fake('OtherHandler', addr=0x6300000 + i) for i in range(3)] + [handler]))
SCRIPT_COUNT = 8   # pawn.TrickData.InstancedScripts entries (unknown live count)
pawn = Fake('Pawn', cls('OakCharacter'), dict(
    Mesh=mesh, bIsCrouched=False, bUseControllerRotationYaw=False, InputComponent=input_component,
    TrickData=Fake('TrickData', props=dict(InstancedScripts=[
        Fake('Script%d' % i, cls('S'), dict(MyActor=None), path='/Script/X.Other') for i in range(SCRIPT_COUNT)])),
    OneHandWeaponActionLock=Fake('Lock', props=dict(bLocked=False))), dict(
    IsCharacterDashing=lambda: False, K2_GetActorRotation=actor_rotation,
    GetLastMovementInputVector=lambda: motion_vector(1.0 if MOTION['speed'] else 0.0),
    GetPendingMovementInputVector=lambda: vec(),
    K2_SetActorRotation=set_actor_rotation), addr=0x70000000)
pawn._d['OakCharacterMovement'] = movement
pawn._d['CharacterMovement'] = movement
camera = Fake('CameraManager', cls('OakPlayerCameraManager'), dict(
    CameraModeState=Fake('ModeState', props=dict(bIsTransitioning=False)),
    CameraModeInputs=Fake('ModeInputs', props=dict(ViewTarget=pawn, Weapon=weapon))), dict(
    GetActorCameraMode=lambda p: 'ThirdPerson', GetCameraRotation=lambda: rot()), addr=0x80000000)

# Enhanced Input: realistic per-role key counts (keyboard + gamepad), 120 rows.
ACTIONS = {'Action_Sprint': 2, 'Action_Dash': 2, 'Action_Crouch_Hold': 2, 'Action_Jump_HoldToGlide': 2,
           'Action_Fire': 2, 'Action_Zoom': 2, 'Action_Gadget': 2, 'Action_Carry_Throw': 2}
MAPPING_ROWS = 120
rows = []
action_cls = cls('GbxEnhancedInputAction', '/Script/GbxEnhancedInput.GbxEnhancedInputAction')
for asset, keys in ACTIONS.items():
    action = Fake(asset, action_cls, dict(Triggers=[]), addr=0x1000 + len(rows),
                  path='/Game/GameData/Input/EnhancedInput/' + asset + '.' + asset)
    for k in range(keys):
        rows.append(Fake('Mapping', props=dict(Action=action, Key=Fake('Key', props=dict(KeyName=asset + str(k))),
                                               bShouldBeIgnored=False, Triggers=[])))
other = Fake('Action_Other', action_cls, dict(Triggers=[]), path='/Game/GameData/Input/EnhancedInput/Action_Other.Action_Other')
while len(rows) < MAPPING_ROWS:
    rows.append(Fake('Mapping', props=dict(Action=other, Key=Fake('Key', props=dict(KeyName='K')),
                                           bShouldBeIgnored=False, Triggers=[])))
player_input = Fake('PlayerInput', support.mapping_schema(), dict(EnhancedActionMappings=rows))
pc = Fake('PlayerController', cls('OakPlayerController'), dict(
    Character=pawn, Pawn=pawn, AcknowledgedPawn=pawn, OakPlayerCameraManager=camera,
    bShowMouseCursor=False, PlayerInput=player_input), dict(
    GetControlRotation=lambda: rot(), IsInputKeyDown=lambda key: False,
    GetInputAnalogKeyState=lambda key: 0.0), addr=0x90000000)

# mods_base.get_pc(): ENGINE.GameViewport.World.OwningGameInstance.LocalPlayers[0].PlayerController
local_player = Fake('LocalPlayer', props=dict(PlayerController=pc))
game_instance = Fake('GameInstance', props=dict(LocalPlayers=[local_player]))
world = Fake('World', props=dict(OwningGameInstance=game_instance))
engine = Fake('Engine', props=dict(GameViewport=Fake('Viewport', props=dict(World=world))))


def get_runtime():
    hit('get_runtime')
    p = engine.GameViewport.World.OwningGameInstance.LocalPlayers[0].PlayerController
    if p is None:
        return None, None, None
    pw = None
    for attribute in ('Character', 'Pawn', 'AcknowledgedPawn'):
        candidate = getattr(p, attribute)
        if candidate is not None:
            pw = candidate
            break
    return p, pw, p.OakPlayerCameraManager


slide_target = Enum('ParentVelocity2D')
slide_asset = Fake('Move_Slide', props=dict(LaunchDirection=Fake('Launch', props=dict(RelativeDirection=slide_target))))

mod = S(_get_runtime=get_runtime, _native_read=native_read, _native_query=native_query, _kernel32=kernel32,
        _third_person_enabled=True, _third_person_pushed=True, _vehicle_camera_active=False,
        _shop_camera_active=False, _ladder_active=False, _slide_active=False, _ads_active=False,
        _ads_route=None, _slide_camera_recovery_pending=False, FIRST_PERSON_ANIM_HOOK='widget',
        CLIENT_RESTART_FUNCTION='restart', SETTINGS_DIR=None)
updates = S(is_game_thread=lambda: kernel32.GetCurrentThreadId() == 7, has_hook=lambda *a: False,
            add_hook=lambda *a: None, remove_hook=lambda *a: None, _owner=S(active=True))

# ------------------------------------------------------------ bound session
from BL4ThirdPersonPOC.omni import settings  # noqa: E402
settings.diagnostics_enabled = lambda: False
from BL4ThirdPersonPOC.omni.inputs import NativeBindings  # noqa: E402
from BL4ThirdPersonPOC.omni.lifecycle import LifecycleSupervisor  # noqa: E402

s = GameplaySession(mod, updates)
s.lifecycle_managed = True
s.refs = tuple(WP(o) for o in (pc, pawn, camera, movement))
s.inputs = NativeBindings(pc)
s.inputs.refresh(require_complete=True)
s.report['optional_field_errors'] = {}
s.combat_refs = tuple(WP(o) for o in (mesh, anim, weapon))
s.head_mesh, s.head_anim = WP(mesh), WP(anim)
s.mesh_ref, s.anim_ref, s.anim_address = WP(mesh), WP(anim), ANIM_ADDR
s.bones = []
for flag in ('ready', 'blend_layout_ready', 'player_ready', 'sprint_ready', 'route_ready', 'vector_ready',
             'entry_ready', 'slide_ready', 'active', 'registered'):
    setattr(s, flag, True)
s.slide_ref, s.slide_target, s.slide_pending = WP(slide_asset), slide_target, True
s.impulse_index, s.follow_started_t, s.follow_previous_t = 1, 0.0, 0.0
s.blend_original, s.blend_pending = True, True
s.phase, s.live_phase, s.live_sprint_phase = 'B_NEUTRAL_YAW', 'FREE_BODY_LEAN_SUPPRESSED', 'IDLE_HOLD'
s.handoff_reason, s.follow_mode = 'GROUNDED_CONTROL', 'IDLE_HOLD'
s.handler_ref, s.component_ref = WP(handler), WP(input_component)
s.handler_address, s.movement_address, s.base = handler._a, MOVE_ADDR, BASE
s.selection_addresses = {'GbxAnimGraphNode_Locomotion_2': ANIM_ADDR + 38928}
s.grenade_facing.supported = True
mem[handler._a + 72] = bytes([0, 1])
DASH_CONFIG = 0x64000000
mem[MOVE_ADDR + 17456] = struct.pack('<Q', DASH_CONFIG)
mem[DASH_CONFIG + 144] = struct.pack('<4f', 0.0, 90.0, 180.0, 270.0)
mem[BASE + 163877400] = struct.pack('<d', math.pi / 180.0)
getter_props = [S(Name='InKey', Class=S(Name='StructProperty'), Offset_Internal=0,
                  Struct=S(_path_name=lambda: '/Script/GameplayTags.GameplayTag')),
                S(Name='ReturnValue', Class=S(Name='ObjectProperty'), Offset_Internal=8,
                  PropertyClass=S(_path_name=lambda: '/Script/Engine.AnimSequenceBase'))]
getter = S(_properties=lambda: getter_props, FunctionFlags=0)
import BL4ThirdPersonPOC.omni.animation as _animation  # noqa: E402
_animation.find_object = lambda kind, path: getter if path.endswith('GetAnimationFromTag') else None
mem[ANIM_ADDR + s.BLEND_OFFSET + 40] = struct.pack('<Q', ANIM_ADDR + s.LEAN_OFFSET)


def own(owner, target):
    size = len(getattr(owner, 'PROLOGUE', b'')) or 14
    patch = (b'\xff\x25' + bytes(64))[:size]
    owner.hook = dict(target=target, patch=patch, patch_attempted=False)
    mem[target] = patch


n = s.native
n.base, n.movement, n.vtable, n.component = BASE, MOVE_ADDR, BASE + 0xB709670, component_obj._a
mem[MOVE_ADDR] = struct.pack('<Q', n.vtable)
mem[MOVE_ADDR + 0x110] = struct.pack('<Q', n.component)
own(n, BASE + 0x100)
for i, owner in enumerate((s.aim_native, s.idle_native, s.idle_update)):
    owner.node, owner.table = ANIM_ADDR + 0x1000 * (i + 1), BASE + 0x7000 + i
    mem[owner.node] = struct.pack('<Q', owner.table)
    own(owner, BASE + 0x200 + i * 0x40)
for owner in (s.idle_native, s.idle_update):
    owner.scope_nodes = tuple(('Idle%d' % k, ANIM_ADDR + 0x20000 + k * 0x100) for k in range(5))
    for _, address in owner.scope_nodes:
        mem[address] = struct.pack('<Q', owner.table)
s.idle_update.table = s.idle_native.table
for _, address in s.idle_update.scope_nodes:
    mem[address] = struct.pack('<Q', s.idle_native.table)
mem[s.idle_update.node] = struct.pack('<Q', s.idle_native.table)
s.aim_native.crouch_node, s.aim_native.crouch_table = ANIM_ADDR + 0x9000, BASE + 0x7100
mem[s.aim_native.crouch_node] = struct.pack('<Q', s.aim_native.crouch_table)
for i, trace in enumerate((s.direction_trace, s.index_trace, s.route, s.dash_branch, s.vector_trace)):
    trace.base, trace.movement = BASE, MOVE_ADDR
    own(trace, BASE + 0x400 + i * 0x40)
s.index_trace.node = ANIM_ADDR + 38928
mem[s.index_trace.node] = struct.pack('<Q', BASE + 0xB09B440)
for action, rva, owner, trace in s.entries:
    owner.base = BASE
    own(trace, BASE + rva)

sup = LifecycleSupervisor(mod, updates)
sup.active, sup.child = True, s
sup.previous_normal_inputs = True

# ------------------------------------------------------- stage attribution
import BL4ThirdPersonPOC.omni.session as session_mod  # noqa: E402

STAGES = set()


def wrap(owner, name, label=None):
    original = getattr(owner, name)
    label = label or name

    def wrapped(*args, **kwargs):
        if ENABLED[0]:
            CALLS[label] += 1
        STACK.append(label)
        try:
            return original(*args, **kwargs)
        finally:
            STACK.pop()
    setattr(owner, name, wrapped)
    STAGES.add(label)


for name in dir(GameplaySession):
    if name.startswith('__'):
        continue
    if callable(getattr(GameplaySession, name)):
        wrap(GameplaySession, name)
for owner in (s.native, s.aim_native, s.idle_native, s.idle_update, s.direction_trace, s.index_trace,
              s.route, s.dash_branch, s.vector_trace, *[t for _, _, _, t in s.entries]):
    for name in ('validate', 'consume', 'consume_slide'):
        if hasattr(owner, name):
            wrap(owner, name, type(owner).__name__ + '.' + name)
wrap(s.inputs, 'snapshot', 'inputs.snapshot')
wrap(s.inputs, 'maybe_refresh', 'inputs.maybe_refresh')
wrap(s.inputs, 'refresh', 'inputs.refresh')
wrap(s.grenade_facing, 'observe', 'grenade.observe')
wrap(sup, 'frame', 'lifecycle.frame')
import BL4ThirdPersonPOC.omni.animation as animation_mod  # noqa: E402
original_guard = animation_mod.validate_visual


def guard(*args, **kwargs):
    STACK.append('visual_guard')
    try:
        return original_guard(*args, **kwargs)
    finally:
        STACK.pop()


animation_mod.validate_visual = guard


import BL4ThirdPersonPOC.omni.sampling as _sampling  # noqa: E402
_sampling.monotonic = lambda: MOTION['t']
s.started = 0.0


def one_frame():
    MOTION['t'] += 1.0 / 60.0
    if SCENARIO == 'turn':
        MOTION['velocity_yaw'] = (MOTION['velocity_yaw'] + 1.5) % 360.0
    movement._d['Velocity'] = motion_vector(MOTION['speed'])
    movement._d['Acceleration'] = motion_vector(MOTION['speed'] and 900.0)
    sup.frame(None, None, None, None)
    s.frame(None, None, None, None)


if SCENARIO == 'crouch':
    pawn._d['bIsCrouched'] = True
if SCENARIO in ('move', 'turn'):
    MOTION['speed'] = 400.0
# Warm-up: first frames set phases/edge state.
for _ in range(3):
    one_frame()
assert s.active, s.report['errors']

FRAMES = 600
ENABLED[0] = True
for _ in range(FRAMES):
    one_frame()
ENABLED[0] = False
assert s.active and not s.report['errors'], s.report['errors']

total = Counter()
for stage, counter in COUNTS.items():
    total.update(counter)
cats = ['get_runtime', 'prop_get', 'prop_set', 'ufunc', 'uobj_eq', 'weak_new', 'weak_deref', 'addr',
        'path_name', 'rpm', 'virtual_query', 'thread_check']
result = dict(scenario=SCENARIO, updates=FRAMES, game_writes=s.report['game_writes'],
              per_update={c: round(total[c] / FRAMES, 3) for c in cats},
              mapping_scans=CALLS['inputs.refresh'], bound_calls_per_update=CALLS['bound'] / FRAMES,
              input_snapshots_per_update=CALLS['inputs.snapshot'] / FRAMES)
if not REPORT:
    print(json.dumps(result))
    sys.exit(0)
print(json.dumps(result, indent=2))


def score(c):
    return c['prop_get'] + 5 * c['ufunc'] + 3 * c['rpm'] + 0.5 * c['weak_deref'] + c['path_name'] * 2


print('\nPER STAGE (self, per update)')
for stage, c in sorted(COUNTS.items(), key=lambda kv: -score(kv[1]))[:30]:
    print('  %-36s ' % stage + ' '.join('%s=%.1f' % (k, c[k] / FRAMES) for k in cats if c[k]))
print('\nUFUNCTIONS per update')
for name, n_ in DETAIL['ufunc'].most_common(12):
    print('  %-50s %6.2f' % (name, n_ / FRAMES))
print('\nPROPERTY READS per update')
for name, n_ in DETAIL['prop_get'].most_common(25):
    print('  %-50s %6.2f' % (name, n_ / FRAMES))
