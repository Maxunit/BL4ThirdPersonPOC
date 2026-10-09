"""Stub environment that imports the real loader package outside the game.

Python-only: it replaces mods_base, unrealsdk and the Windows kernel32 API so
BL4ThirdPersonPOC/__init__.py executes and its enable/disable wiring can be
driven. It proves import health, registration order and cleanup bookkeeping,
not native or gameplay behaviour.
"""
import argparse
import ctypes
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace as S

REPO = Path(__file__).resolve().parents[1]
LOG = []
HOOKS = {}
SETTINGS = Path(tempfile.mkdtemp(prefix='bl4tps_settings_'))


def _log(level):
    return lambda message, *args, **kwargs: LOG.append((level, str(message)))


# ---------------------------------------------------------------- unrealsdk
sdk = types.ModuleType('unrealsdk')
logging_module = types.ModuleType('unrealsdk.logging')
for _level in ('error', 'warning', 'info', 'dev_warning', 'misc'):
    setattr(logging_module, _level, _log(_level))
hooks_module = types.ModuleType('unrealsdk.hooks')


class Type:
    PRE = 'PRE'
    POST = 'POST'
    POST_UNCONDITIONAL = 'POST_UNCONDITIONAL'


class Block:
    pass


def add_hook(func, kind, identifier, callback):
    HOOKS[(func, kind, identifier)] = callback
    return True


def has_hook(func, kind, identifier):
    return (func, kind, identifier) in HOOKS


def remove_hook(func, kind, identifier):
    return HOOKS.pop((func, kind, identifier), None) is not None


hooks_module.Type = Type
hooks_module.Block = Block
hooks_module.add_hook = add_hook
hooks_module.has_hook = has_hook
hooks_module.remove_hook = remove_hook
hooks_module.prevent_hooking_direct_calls = lambda: None


class _Enum:
    def __getattr__(self, name):
        return name


unreal = types.ModuleType('unrealsdk.unreal')
unreal.WeakPointer = lambda obj: (lambda: obj)
sdk.logging = logging_module
sdk.hooks = hooks_module
sdk.unreal = unreal
sdk.find_all = lambda *args, **kwargs: []
sdk.find_object = lambda *args, **kwargs: None
sdk.find_class = lambda *args, **kwargs: S(ClassDefaultObject=None, Name=str(args[0]) if args else '')
sdk.find_enum = lambda *args, **kwargs: _Enum()
sdk.make_struct = lambda *args, **kwargs: S(**kwargs)
sdk.construct_object = lambda *args, **kwargs: S()
sdk.load_package = lambda *args, **kwargs: None
sys.modules.update({'unrealsdk': sdk, 'unrealsdk.logging': logging_module,
                    'unrealsdk.hooks': hooks_module, 'unrealsdk.unreal': unreal})

# ---------------------------------------------------------------- mods_base
mods_base = types.ModuleType('mods_base')


class Option:
    def __init__(self, identifier, value=None, *args, **kwargs):
        self.identifier = identifier
        self.value = value
        self.args = args
        self.__dict__.update(kwargs)


class KeybindObject:
    def __init__(self, identifier, key, callback, **kwargs):
        self.identifier = identifier
        self.key = key
        self.default_key = key
        self.callback = callback
        self.is_enabled = False
        self.__dict__.update(kwargs)

    def enable(self):
        self.is_enabled = True

    def disable(self):
        self.is_enabled = False

    def __call__(self, *args):
        return self.callback(*args)


def keybind(identifier, key=None, callback=None, **kwargs):
    if callback is not None:
        return KeybindObject(identifier, key, callback, **kwargs)
    return lambda function: KeybindObject(identifier, key, function, **kwargs)


class CommandObject:
    def __init__(self, cmd, callback, description=''):
        self.cmd = cmd
        self.callback = callback
        self.parser = argparse.ArgumentParser(prog=cmd)
        self.enabled = False

    def add_argument(self, *args, **kwargs):
        return self.parser.add_argument(*args, **kwargs)

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def run(self, line=''):
        self.callback(self.parser.parse_args(line.split()))

    def __call__(self, args):
        self.callback(args)


def command(cmd, **kwargs):
    return lambda function: CommandObject(cmd, function, kwargs.get('description', ''))


class KeybindOption(Option):
    @staticmethod
    def from_keybind(bind):
        return KeybindOption(bind.identifier, bind.key)


class Game:
    BL4 = 'BL4'

    @staticmethod
    def get_current():
        return 'BL4'


BUILT = {}


def build_mod(**kwargs):
    mod = S(**kwargs)
    mod.save_settings = lambda: None
    BUILT['mod'] = mod
    return mod


mods_base.BoolOption = Option
mods_base.SliderOption = Option
mods_base.KeybindOption = KeybindOption
mods_base.EInputEvent = S(IE_Pressed='IE_Pressed', IE_Released='IE_Released',
                          IE_Repeat='IE_Repeat', IE_DoubleClick='IE_DoubleClick', IE_Axis='IE_Axis')
mods_base.Game = Game
mods_base.SETTINGS_DIR = SETTINGS
mods_base.build_mod = build_mod
mods_base.command = command
mods_base.get_pc = lambda: None
mods_base.keybind = keybind
mods_base.open_in_mod_dir = None
sys.modules['mods_base'] = mods_base


# ---------------------------------------------------------------- kernel32
class FakeFunction:
    def __init__(self, name, impl):
        self.name = name
        self.impl = impl

    def __call__(self, *args):
        return self.impl(*args)


THREAD_ID = 4242


class FakeKernel:
    def __init__(self):
        self.functions = {}

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        functions = self.__dict__['functions']
        if name not in functions:
            impl = {
                'GetCurrentThreadId': lambda *a: THREAD_ID,
                'GetCurrentProcess': lambda *a: -1,
                'GetModuleHandleW': lambda *a: 0x140000000 if not a or a[0] is None else 0,
            }.get(name, lambda *a: 0)
            functions[name] = FakeFunction(name, impl)
        return functions[name]


KERNEL = FakeKernel()
ctypes.WinDLL = lambda *args, **kwargs: KERNEL
if not hasattr(ctypes, 'WINFUNCTYPE'):
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
if not hasattr(ctypes, 'get_last_error'):
    ctypes.get_last_error = lambda: 0

sys.path.insert(0, str(REPO))


def load():
    import BL4ThirdPersonPOC as loader
    return loader


def set_build(reviewed):
    from BL4ThirdPersonPOC import build_gate
    identity = build_gate.REVIEWED_BUILD if reviewed else (0x11111111, 0x31B8C000, 0x8664)
    build_gate._cache['status'] = dict(
        build=identity, label=build_gate.REVIEWED_BUILDS.get(identity), reviewed=reviewed,
        store='steam' if reviewed else 'epic', executable='', reason='' if reviewed else 'test')


def enable_entry_points(loader):
    for entry in tuple(loader._MOD_KEYBINDS) + tuple(loader._MOD_COMMANDS):
        entry.enable()


def bind_game_thread(loader):
    """Mark the current thread as the owned game thread of runtime_updates."""
    from BL4ThirdPersonPOC import runtime_updates
    if runtime_updates._owner is not None:
        runtime_updates._owner.thread = THREAD_ID
