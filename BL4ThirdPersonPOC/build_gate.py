"""Central game-build identity and store detection for every native feature.

All native RVAs, prologues and code hashes in this mod were measured on exactly
one executable. Its PE identity is (TimeDateStamp, SizeOfImage, Machine).
Native modules still verify their own code bytes before patching; this module
is the single place that names the reviewed build and decides, once per
process, whether the loader may install anything at all.

Store detection (Steam / Epic) is informational: it explains a refusal, it
never authorises a build. Supporting another build means adding its identity
here AND its own measured RVA/byte tables in each native module.
"""
import ctypes
import struct

# Steam build of 2026-09-14 (TimeDateStamp 0x6AA81051 = 2026-09-14 15:18:41 UTC).
STEAM_2026_09_14 = (0x6AA81051, 0x31B8C000, 0x8664)

# Builds whose complete native tables have been measured and reviewed.
REVIEWED_BUILDS = {
    STEAM_2026_09_14: 'steam-2026-09-14',
}

# The build every native table in this package was measured on.
REVIEWED_BUILD = STEAM_2026_09_14

_cache = {}


def parse_pe_identity(read, base):
    """Read (TimeDateStamp, SizeOfImage, Machine) from a loaded x64 image."""
    dos = read(base, 64)
    if dos[:2] != b'MZ':
        raise RuntimeError('DOS signature differs')
    offset = struct.unpack_from('<I', dos, 60)[0]
    if not 64 <= offset <= 0x100000:
        raise RuntimeError('PE header offset outside bounds')
    pe = read(base + offset, 0x108)
    if pe[:4] != b'PE\0\0':
        raise RuntimeError('PE signature differs')
    if struct.unpack_from('<H', pe, 24)[0] != 0x20B:
        raise RuntimeError('Optional header is not PE32+')
    return (struct.unpack_from('<I', pe, 8)[0],
            struct.unpack_from('<I', pe, 80)[0],
            struct.unpack_from('<H', pe, 4)[0])


def _module_loaded(kernel32, name):
    try:
        return bool(kernel32.GetModuleHandleW(name))
    except Exception:
        return False


def _executable_path():
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetModuleFileNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32)
        kernel32.GetModuleFileNameW.restype = ctypes.c_uint32
        buffer = ctypes.create_unicode_buffer(1024)
        length = kernel32.GetModuleFileNameW(None, buffer, len(buffer))
        return buffer.value[:length] if length else ''
    except Exception:
        return ''


def detect_store(kernel32, executable=''):
    """Best-effort store hint from loaded platform DLLs and the install path."""
    path = executable.replace('/', '\\').lower()
    if _module_loaded(kernel32, 'steam_api64.dll') or '\\steamapps\\' in path:
        return 'steam'
    if '\\epic games\\' in path or _module_loaded(kernel32, 'EOSSDK-Win64-Shipping.dll'):
        return 'epic'
    return 'unknown'


def evaluate(read, kernel32, executable=''):
    """Pure evaluation used by status(); also the unit-test entry point."""
    result = dict(build=None, label=None, reviewed=False, store='unknown',
                  executable=executable, reason='')
    try:
        base = int(kernel32.GetModuleHandleW(None) or 0)
        if not base:
            raise RuntimeError('Main module handle unavailable')
        build = parse_pe_identity(read, base)
        result['build'] = build
        result['label'] = REVIEWED_BUILDS.get(build)
        result['reviewed'] = build in REVIEWED_BUILDS
        if not result['reviewed']:
            result['reason'] = 'executable identity differs from every reviewed build'
    except Exception as exc:
        result['reason'] = 'build identity unreadable: ' + repr(exc)[:200]
    result['store'] = detect_store(kernel32, executable)
    return result


def status(owner_module):
    """Cached per process: the executable cannot change while the game runs."""
    if 'status' not in _cache:
        _cache['status'] = evaluate(owner_module._native_read, owner_module._kernel32,
                                    _executable_path())
    return dict(_cache['status'])


def summary(result):
    build = result.get('build')
    shown = 'unreadable' if build is None else '/'.join(hex(v) for v in build)
    reviewed = ', '.join(label + '=' + '/'.join(hex(v) for v in identity)
                         for identity, label in REVIEWED_BUILDS.items())
    return ('build=' + shown + ' store=' + str(result.get('store')) + ' reviewed=['
            + reviewed + '] reason=' + str(result.get('reason') or 'ok'))
