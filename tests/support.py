"""Small SDK substitutes for Python-only ownership/input/cleanup tests."""
import sys
import types
from pathlib import Path
from types import SimpleNamespace as S

REPO_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_DIR / 'BL4ThirdPersonPOC'
sys.path.insert(0, str(REPO_DIR))

# Load BL4ThirdPersonPOC submodules without executing the loader __init__
# (it needs mods_base and the Windows kernel32 API).
if 'BL4ThirdPersonPOC' not in sys.modules:
    package = types.ModuleType('BL4ThirdPersonPOC')
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules['BL4ThirdPersonPOC'] = package

LOG = []
sdk = types.ModuleType('unrealsdk')
sdk.hooks = types.ModuleType('unrealsdk.hooks')
sdk.hooks.Type = S(PRE=0, POST=2, POST_UNCONDITIONAL=1)
sdk.hooks.Block = type('Block', (), {})
sdk.hooks.add_hook = sdk.hooks.remove_hook = lambda *args, **kwargs: None
sdk.hooks.has_hook = lambda *args: False
sys.modules['unrealsdk.hooks'] = sdk.hooks
sdk.logging = S(warning=lambda m: LOG.append(('warning', m)), error=lambda m: LOG.append(('error', m)),
                info=lambda m: LOG.append(('info', m)), dev_warning=lambda m: LOG.append(('dev_warning', m)))
sdk.make_struct = lambda *args, **kwargs: S(**kwargs)
sdk.find_object = lambda *args: None
sdk.find_enum = lambda *args: None
unreal = types.ModuleType('unrealsdk.unreal')
unreal.WeakPointer = lambda obj: lambda: obj
sys.modules['unrealsdk'] = sdk
sys.modules['unrealsdk.unreal'] = unreal


def prop(name, kind, offset, **kw):
    return S(Name=name, Class=S(Name=kind), Offset_Internal=offset, **kw)


def mapping_schema(offset=1344):
    key_struct = S(_path_name=lambda: '/Script/InputCore.Key')
    fields = [prop('Action', 'ObjectProperty', 32),
              prop('Key', 'StructProperty', 40, Struct=key_struct),
              prop('bShouldBeIgnored', 'BoolProperty', 64), prop('Triggers', 'ArrayProperty', 0)]
    struct = S(Name='EnhancedActionKeyMapping', _superfields=lambda: (), _properties=lambda: fields)
    array = prop('EnhancedActionMappings', 'ArrayProperty', offset,
                 Inner=S(Class=S(Name='StructProperty'), Struct=struct))
    return S(_path_name=lambda: '/Script/GbxEnhancedInput.GbxEnhancedPlayerInput',
             _superfields=lambda: (), _properties=lambda: [array])


def mapping(asset, key, ignored=False, triggers=()):
    action = S(_path_name=lambda: '/Game/GameData/Input/EnhancedInput/' + asset + '.' + asset,
               Class=S(_path_name=lambda: '/Script/GbxEnhancedInput.GbxEnhancedInputAction'),
               _get_address=lambda: sum(map(ord, asset)), Triggers=[])
    return S(Action=action, Key=S(KeyName=key), bShouldBeIgnored=ignored, Triggers=triggers)


def controller():
    names = ['Action_Sprint', 'Action_Dash', 'Action_Crouch_Hold',
             'Action_Jump_HoldToGlide', 'Action_Fire', 'Action_Zoom']
    rows = [mapping(asset, 'UserBinding_' + str(i)) for i, asset in enumerate(names)]
    pc = S(PlayerInput=S(Class=mapping_schema(), EnhancedActionMappings=rows), pressed=set(), analog={})
    pc.IsInputKeyDown = lambda key: str(key.KeyName) in pc.pressed
    pc.GetInputAnalogKeyState = lambda key: pc.analog.get(str(key.KeyName), 0.0)
    return pc


def session():
    from BL4ThirdPersonPOC.omni.session import GameplaySession
    mod = S(_on_disable_impl=lambda: None, FIRST_PERSON_ANIM_HOOK='widget',
            CLIENT_RESTART_FUNCTION='restart')
    subscriptions = set()
    updates = S(is_game_thread=lambda: True,
                has_hook=lambda *args: args in subscriptions,
                remove_hook=lambda *args: subscriptions.discard(args),
                add_hook=lambda *args: subscriptions.add(args[:-1]))
    obj = GameplaySession(mod, updates)
    obj.lifecycle_managed = True
    return obj, subscriptions
