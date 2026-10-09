"""Read-only fire-path probe for the unified rear-blocker correction.

The Beam rear-blocker fix lives in FireBeam-only code (receiver mode 5, radius-20
sweep at RVA 0xA65AF1). Projectile and hitscan weapons aim through another
native path that is not yet measured. This probe collects what is needed to
find it offline, without changing anything:

- the equipped weapon's use-mode table and its behaviors (class, vtable),
- the fire behavior's override slots (vtable entries unique among the weapon's
  behaviors) and a bounded static harvest of the code they reach,
- anchors: reads of the camera-cache location (manager +0x1910, measured by the
  Beam guards) and calls into the known Beam query helper,
- pointer-to-object fields of the fire behavior (receivers/targeting helpers).

Only ReadProcessMemory is used. Code reads stay inside executable sections of
the reviewed build; a different build is refused before any code read.
"""
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from .build_gate import REVIEWED_BUILD, parse_pe_identity

TAG = '[BL4ThirdPersonPOC.WeaponProbe]'
VERSION = 'weapon-fire-path-probe-3'
REPORT_DIRECTORY_NAME = 'BL4ThirdPersonPOC_reports'
REPORT_PREFIX = 'weapon_probe_'
MAX_REPORTS = 12

MAX_BEHAVIORS = 64
VTABLE_SLOTS = 0x600 // 8
USE_MODE_TABLE = 0xBE8      # (data, count, capacity) – measured by the Beam owner
USE_MODE_INDEX = 0xBD8
USE_MODE_STRIDE = 0x88
OBJECT_WINDOW = 0x600
FUNCTION_WINDOW = 0x700
MAX_FUNCTIONS = 160
MAX_DEPTH = 3
# Weapon holder interface (TScriptInterface at OakWeapon +0xB18/+0xB20). Measured
# in round 1: the shared fire slot 0x2C0 asks it for the aim target (+0x38) and
# 0x3EC656E for the fire rotation (+0x48). Its code is harvested separately.
HOLDER_OBJECT = 0xB18
HOLDER_INTERFACE = 0xB20
HOLDER_SLOTS = 32
HOLDER_ENTRY_SLOTS = (0x30, 0x38, 0x40, 0x48, 0x50)
HOLDER_WINDOW = 0x1000
HOLDER_FUNCTIONS = 40
HOLDER_DEPTH = 2
# Round 2: holder +0x38 (OakCharacter, interface at +0x3A30) asks the local
# controller's aim provider: qword(PC + 0x448), vfunc 0x878 (aim valid) and
# vfunc 0x730 (aim target vector). Fallback: pawn vfunc 0x718.
AIM_PROVIDER = 0x448
AIM_VALID_SLOT = 0x878
AIM_TARGET_SLOT = 0x730
PAWN_AIM_FALLBACK_SLOT = 0x718
PROVIDER_SLOTS = 0xA00 // 8
PROVIDER_WINDOW = 0x1000
PROVIDER_FUNCTIONS = 260
PROVIDER_DEPTH = 3
# Beam owner validated OakPlayerCameraManager vfunc 0x878 == 0x4904A5C.
MEASURED_MANAGER_AIM_VALID = 0x4904A5C
# Fire pipeline windows (slot 0x410 use, 0x490 spawn) in full length.
FIRE_WINDOWS = ((0x410, 0x2400), (0x490, 0x1000), (0x2C0, 0x100), (0x2C8, 0x100))
CAMERA_CACHE_LOCATION = 0x1910
# Camera cache POV (location at +0x1910, rotation follows): any disp32 in range.
CAMERA_CACHE_RANGE = (0x1900, 0x1960)
MAX_SUBOBJECTS = 16
BEAM_RECEIVER_VTABLE = 0xB7931C0
RECEIVER_SLOTS = (0x300, 0x308, 0x368)
MAX_DUMP = 0x4000
KNOWN = {
    0x38F90E: 'beam_query_helper',
    0x20A8: 'native_cleanup',
    0x4344586: 'firebeam_slot_0x410',
    0xA640F0: 'beam_endpoint_producer',
    0xA65AF1: 'beam_collision_capture_site',
}


class Image:
    """Executable ranges of the loaded main module."""

    def __init__(self, read, base):
        self.read, self.base = read, base
        dos = read(base, 64)
        offset = struct.unpack_from('<I', dos, 60)[0]
        pe = read(base + offset, 24)
        sections, optional_size = struct.unpack_from('<H', pe, 6)[0], struct.unpack_from('<H', pe, 20)[0]
        optional = read(base + offset + 24, optional_size)
        self.size = struct.unpack_from('<I', optional, 56)[0]
        table = read(base + offset + 24 + optional_size, sections * 40)
        self.executable = []
        for i in range(sections):
            virtual_size, rva, raw_size = struct.unpack_from('<III', table, i * 40 + 8)
            flags = struct.unpack_from('<I', table, i * 40 + 36)[0]
            span = max(virtual_size, raw_size)
            if flags & 0x20000000 and span and rva + span <= self.size:
                self.executable.append((rva, rva + span))

    def in_image(self, address):
        return self.base <= address < self.base + self.size

    def code_rva(self, address):
        rva = address - self.base
        return rva if any(lo <= rva < hi for lo, hi in self.executable) else None

    def code(self, rva, length):
        hi = next(hi for lo, hi in self.executable if lo <= rva < hi)
        return self.read(self.base + rva, max(1, min(length, hi - rva)))


def qword(read, address):
    return struct.unpack('<Q', read(address, 8))[0]


def scan_calls(code, rva, image):
    """Direct call/jmp rel32 and call [rip+disp32] targets inside executable code.

    Linear byte scanning may report a few false targets; they only cost budget.
    """
    targets = []
    for i in range(len(code) - 4):
        op = code[i]
        if op in (0xE8, 0xE9) and i + 5 <= len(code):
            target = rva + i + 5 + struct.unpack_from('<i', code, i + 1)[0]
            if image.code_rva(image.base + target) is not None:
                targets.append(('call' if op == 0xE8 else 'jmp', i, target))
        elif op == 0xFF and code[i + 1] == 0x15 and i + 6 <= len(code):
            slot = image.base + rva + i + 6 + struct.unpack_from('<i', code, i + 2)[0]
            if image.in_image(slot):
                try:
                    pointer = qword(image.read, slot)
                except Exception:
                    continue
                target = image.code_rva(pointer)
                if target is not None:
                    targets.append(('call_indirect', i, target))
    return targets


def anchors(code):
    """Offsets of disp32 values inside the camera-cache POV range (+0x1900..+0x1960)."""
    found = []
    lo, hi = CAMERA_CACHE_RANGE
    for index in range(len(code) - 3):
        if code[index + 2] == 0 and code[index + 3] == 0:
            value = struct.unpack_from('<I', code, index)[0]
            if lo <= value < hi:
                found.append(index)
    return found


def harvest(image, entries, window=None, budget=None, max_depth=None):
    """Breadth-first bounded harvest from entry RVAs; returns rva -> record."""
    window = FUNCTION_WINDOW if window is None else window
    budget = MAX_FUNCTIONS if budget is None else budget
    max_depth = MAX_DEPTH if max_depth is None else max_depth
    functions, queue = {}, [(rva, 0, 'entry') for rva in entries]
    while queue and len(functions) < budget:
        rva, depth, source = queue.pop(0)
        if rva in functions:
            continue
        try:
            code = image.code(rva, window)
        except Exception as exc:
            functions[rva] = dict(depth=depth, source=source, error=repr(exc)[:160])
            continue
        calls = scan_calls(code, rva, image)
        record = dict(depth=depth, source=source, hex=code.hex(),
                      camera_cache_reads=anchors(code),
                      known_calls=sorted({KNOWN[t] for _, _, t in calls if t in KNOWN}),
                      calls=[dict(kind=k, at=o, target=hex(t)) for k, o, t in calls[:96]])
        if rva in KNOWN:
            record['known'] = KNOWN[rva]
        functions[rva] = record
        if depth < max_depth:
            for kind, _, target in calls:
                if kind != 'jmp' or not 0 <= target - rva < window:  # skip local branches
                    queue.append((target, depth + 1, hex(rva)))
    return functions


def vtable(read, image, obj):
    table = qword(read, obj)
    if not image.in_image(table):
        raise RuntimeError('Object vtable outside main module')
    raw = read(table, VTABLE_SLOTS * 8)
    slots = []
    for i in range(VTABLE_SLOTS):
        target = image.code_rva(struct.unpack_from('<Q', raw, i * 8)[0])
        slots.append(target)
    return table - image.base, slots


def object_pointers(read, image, obj):
    """Fields of the object that point to other objects with a module vtable."""
    raw = read(obj, OBJECT_WINDOW)
    found = []
    for offset in range(8, OBJECT_WINDOW, 8):
        value = struct.unpack_from('<Q', raw, offset)[0]
        if value < 0x10000 or image.in_image(value) or value >= 1 << 47:
            continue
        try:
            first = qword(read, value)
        except Exception:
            continue
        if image.in_image(first):
            found.append(dict(offset=hex(offset), object=hex(value), vtable_rva=hex(first - image.base)))
    return found, raw.hex()


def describe(obj):
    try:
        return dict(name=str(obj.Name), cls=str(obj.Class.Name), path=str(obj._path_name()),
                    address=int(obj._get_address()))
    except Exception as exc:
        return dict(error=repr(exc)[:160])


def holder(read, image, wa, runtime):
    """Weapon holder interface: object, interface vtable, slots and identity."""
    obj, iface = qword(read, wa + HOLDER_OBJECT), qword(read, wa + HOLDER_INTERFACE)
    row = dict(object=hex(obj), interface=hex(iface))
    if not obj or not iface:
        row['missing'] = True
        return row, []
    row['interface_offset'] = hex(iface - obj)
    row['matches'] = [name for name, address in runtime.items() if address == obj]
    object_vtable = qword(read, obj)
    row['object_vtable_rva'] = hex(object_vtable - image.base) if image.in_image(object_vtable) else None
    table = qword(read, iface)
    if not image.in_image(table):
        raise RuntimeError('Holder interface vtable outside main module')
    raw = read(table, HOLDER_SLOTS * 8)
    slots = [image.code_rva(struct.unpack_from('<Q', raw, i * 8)[0]) for i in range(HOLDER_SLOTS)]
    row['interface_vtable_rva'] = hex(table - image.base)
    row['slots'] = [None if rva is None else hex(rva) for rva in slots]
    entries = [slots[o // 8] for o in HOLDER_ENTRY_SLOTS if slots[o // 8] is not None]
    return row, entries


def aim_provider(read, image, runtime):
    """Controller aim provider (PC +0x448): identity, vtable slots and entries."""
    pc = runtime.get('controller')
    if not pc:
        return dict(missing='controller'), []
    obj = qword(read, pc + AIM_PROVIDER)
    row = dict(address=hex(obj), matches=[name for name, address in runtime.items() if address == obj])
    if not obj:
        row['missing'] = 'provider'
        return row, []
    table = qword(read, obj)
    if not image.in_image(table):
        raise RuntimeError('Aim provider vtable outside main module')
    raw = read(table, PROVIDER_SLOTS * 8)
    slots = [image.code_rva(struct.unpack_from('<Q', raw, i * 8)[0]) for i in range(PROVIDER_SLOTS)]
    row.update(vtable_rva=hex(table - image.base), slots=[None if r is None else hex(r) for r in slots])
    row['aim_valid'] = None if slots[AIM_VALID_SLOT // 8] is None else hex(slots[AIM_VALID_SLOT // 8])
    row['aim_target'] = None if slots[AIM_TARGET_SLOT // 8] is None else hex(slots[AIM_TARGET_SLOT // 8])
    row['aim_valid_matches_beam_measurement'] = slots[AIM_VALID_SLOT // 8] == MEASURED_MANAGER_AIM_VALID
    entries = [slots[o // 8] for o in (AIM_TARGET_SLOT, AIM_VALID_SLOT) if slots[o // 8] is not None]
    pawn = runtime.get('pawn')
    if pawn:
        pawn_table = qword(read, pawn)
        if image.in_image(pawn_table):
            fallback = image.code_rva(qword(read, pawn_table + PAWN_AIM_FALLBACK_SLOT))
            row['pawn_aim_fallback'] = None if fallback is None else hex(fallback)
            if fallback is not None:
                entries.append(fallback)
    return row, entries


def fire_windows(image, fire_slots):
    """Full-length windows of the shared fire pipeline slots."""
    windows = {}
    for slot, length in FIRE_WINDOWS:
        rva = fire_slots[slot // 8]
        if rva is None:
            continue
        code = image.code(rva, length)
        windows[hex(slot)] = dict(rva=hex(rva), hex=code.hex(), camera_cache_reads=anchors(code),
                                  calls=[dict(kind=k, at=o, target=hex(t))
                                         for k, o, t in scan_calls(code, rva, image)[:512]])
    return windows


def probe(read, base, weapon, manager, runtime=None):
    """Collect the report for one equipped weapon. Raises on a foreign build."""
    identity = parse_pe_identity(read, base)
    if identity != REVIEWED_BUILD:
        raise RuntimeError('Build differs from the reviewed build; no code read')
    image = Image(read, base)
    report = dict(version=VERSION, utc=datetime.now(timezone.utc).isoformat(),
                  build=[hex(v) for v in identity], known={hex(k): v for k, v in KNOWN.items()},
                  weapon=describe(weapon), errors=[])
    wa = int(weapon._get_address())
    data, count, capacity = struct.unpack('<Qii', read(wa + USE_MODE_TABLE, 16))
    index = read(wa + USE_MODE_INDEX, 1)[0]
    if not 0 <= index < count <= capacity <= 32:
        raise RuntimeError('Weapon use-mode bounds differ')
    modes = []
    for mode in range(count):
        raw = read(data + mode * USE_MODE_STRIDE, USE_MODE_STRIDE)
        modes.append(dict(index=mode, hex=raw.hex(),
                          pointers={hex(o): hex(struct.unpack_from('<Q', raw, o)[0])
                                    for o in range(0, USE_MODE_STRIDE, 8)
                                    if struct.unpack_from('<Q', raw, o)[0] >= 0x10000}))
    report['use_modes'] = dict(current=index, count=count, modes=modes)
    fire = qword(read, data + index * USE_MODE_STRIDE + 8)
    report['fire_object'] = hex(fire)

    behaviors, tables = [], {}
    for position, behavior in enumerate(tuple(getattr(weapon, 'behaviors', ()))[:MAX_BEHAVIORS]):
        row = describe(behavior)
        row['index'] = position
        try:
            table_rva, slots = vtable(read, image, row['address'])
            row['vtable_rva'] = hex(table_rva)
            tables[row['address']] = slots
        except Exception as exc:
            row['vtable_error'] = repr(exc)[:160]
        row['is_current_fire'] = row.get('address') == fire
        row['in_current_use_mode'] = hex(row.get('address', 0)) in modes[index]['pointers'].values()
        behaviors.append(row)
    report['behaviors'] = behaviors

    fire_row = next((b for b in behaviors if b.get('is_current_fire')), None)
    if fire_row is None:
        report['errors'].append('Fire object is not among weapon.behaviors; using raw vtable')
        _, fire_slots = vtable(read, image, fire)
    else:
        fire_slots = tables[fire]
    others = [slots for address, slots in tables.items() if address != fire]
    overrides = [(i, rva) for i, rva in enumerate(fire_slots)
                 if rva is not None and not any(len(s) > i and s[i] == rva for s in others)]
    report['fire'] = dict(
        cls=None if fire_row is None else fire_row.get('cls'),
        slot_0x410=None if fire_slots[0x410 // 8] is None else hex(fire_slots[0x410 // 8]),
        is_measured_firebeam=fire_slots[0x410 // 8] == 0x4344586,
        override_slots=[dict(slot=hex(i * 8), rva=hex(rva)) for i, rva in overrides],
        all_slots=[None if rva is None else hex(rva) for rva in fire_slots])
    pointers, raw = object_pointers(read, image, fire)
    report['fire']['object_pointers'] = pointers
    report['fire']['object_hex'] = raw
    # Sub-objects (receivers/targeting helpers): full slot lists, and the slots
    # the Beam receiver uses (0x300/0x308 identity, 0x368 endpoint producer).
    receiver_entries = []
    for row in pointers[:MAX_SUBOBJECTS]:
        try:
            _, slots = vtable(read, image, int(row['object'], 16))
        except Exception as exc:
            row['vtable_error'] = repr(exc)[:160]
            continue
        row['slots'] = [None if rva is None else hex(rva) for rva in slots]
        row['is_measured_beam_receiver'] = row['vtable_rva'] == hex(BEAM_RECEIVER_VTABLE)
        receiver_entries += [slots[o // 8] for o in RECEIVER_SLOTS if slots[o // 8] is not None]

    entries = [rva for _, rva in overrides]
    if fire_slots[0x410 // 8] is not None and fire_slots[0x410 // 8] not in entries:
        entries.insert(0, fire_slots[0x410 // 8])
    entries += [rva for rva in receiver_entries if rva not in entries]
    functions = harvest(image, entries)
    report['fire']['windows'] = fire_windows(image, fire_slots)
    runtime = dict(runtime or {})
    report['runtime'] = {name: hex(address) for name, address in runtime.items()}
    holder_row, holder_entries = holder(read, image, wa, runtime)
    report['holder'] = holder_row
    holder_functions = harvest(image, holder_entries, window=HOLDER_WINDOW,
                               budget=HOLDER_FUNCTIONS, max_depth=HOLDER_DEPTH)
    report['holder_functions'] = {hex(rva): record for rva, record in holder_functions.items()}
    try:
        provider_row, provider_entries = aim_provider(read, image, runtime)
    except Exception as exc:
        provider_row, provider_entries = dict(error=repr(exc)[:200]), []
    report['aim_provider'] = provider_row
    provider_functions = harvest(image, provider_entries, window=PROVIDER_WINDOW,
                                 budget=PROVIDER_FUNCTIONS, max_depth=PROVIDER_DEPTH)
    report['aim_provider_functions'] = {hex(rva): record for rva, record in provider_functions.items()}
    report['functions'] = {hex(rva): record for rva, record in functions.items()}
    report['summary'] = dict(
        functions=len(functions), override_slots=len(overrides),
        camera_cache_readers=sorted(hex(r) for r, f in functions.items() if f.get('camera_cache_reads')),
        holder_functions=len(holder_functions),
        holder_camera_cache_readers=sorted(hex(r) for r, f in holder_functions.items()
                                           if f.get('camera_cache_reads')),
        holder_beam_helper_callers=sorted(hex(r) for r, f in holder_functions.items()
                                          if 'beam_query_helper' in f.get('known_calls', ())),
        aim_provider_functions=len(provider_functions),
        aim_provider_camera_cache_readers=sorted(hex(r) for r, f in provider_functions.items()
                                                 if f.get('camera_cache_reads')),
        aim_provider_beam_helper_callers=sorted(hex(r) for r, f in provider_functions.items()
                                                if 'beam_query_helper' in f.get('known_calls', ())),
        beam_helper_callers=sorted(hex(r) for r, f in functions.items()
                                   if 'beam_query_helper' in f.get('known_calls', ())))
    if manager is not None:
        ma = int(manager._get_address())
        report['camera_cache_location'] = list(struct.unpack('<3d', read(ma + CAMERA_CACHE_LOCATION, 24)))
    return report


def write(settings_dir, report):
    directory = Path(settings_dir) / REPORT_DIRECTORY_NAME
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    cls = (report.get('fire') or {}).get('cls') or 'unknown'
    path = directory / f'{REPORT_PREFIX}{cls}_{stamp}.json'
    path.write_text(json.dumps(report, separators=(',', ':')), encoding='utf-8')
    try:
        old = sorted(directory.glob(REPORT_PREFIX + '*.json'), key=lambda p: p.stat().st_mtime)
        for stale in old[:-MAX_REPORTS]:
            if stale != path:
                stale.unlink()
    except OSError:
        pass
    return path


def live_aim(read, base, report, manager_address, pawn, call=None):
    """Optional: call the provider's two getters once and relate the target to camera and pawn.

    Only when the provider IS the camera manager and its aim-valid slot is the
    one the Beam owner measured. Same ABI as the game's own call site
    (rcx=provider, rdx=out). No memory is written by this module.
    """
    provider = report.get('aim_provider') or {}
    if provider.get('matches') != ['manager'] or not provider.get('aim_valid_matches_beam_measurement'):
        return dict(skipped='provider is not the measured camera manager')
    valid_rva, target_rva = int(provider['aim_valid'], 16), int(provider['aim_target'], 16)
    if call is None:
        import ctypes

        def call(rva, *args):
            if rva == valid_rva:
                function = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(base + rva)
                return bool(function(*args))
            out = ctypes.create_string_buffer(64)
            function = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(base + rva)
            function(args[0], ctypes.addressof(out))
            return out.raw[:24]
    valid = call(valid_rva, manager_address)
    if not valid:
        # The game only asks for the target after this check succeeds.
        return dict(valid=False)
    target = list(struct.unpack('<3d', call(target_rva, manager_address)))
    camera = list(struct.unpack('<3d', read(manager_address + CAMERA_CACHE_LOCATION, 24)))
    rotation = list(struct.unpack('<3d', read(manager_address + CAMERA_CACHE_LOCATION + 24, 24)))
    location = pawn.K2_GetActorLocation()
    pawn_location = [float(location.X), float(location.Y), float(location.Z)]
    import math
    pitch, yaw = math.radians(rotation[0]), math.radians(rotation[1])
    forward = [math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)]

    def sub(a, b):
        return [x - y for x, y in zip(a, b)]

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    to_target, to_pawn = sub(target, camera), sub(pawn_location, camera)
    return dict(valid=valid, target=target, camera=camera, camera_rotation=rotation,
                camera_forward=forward, pawn=pawn_location,
                target_distance=math.sqrt(dot(to_target, to_target)),
                target_depth=dot(to_target, forward), pawn_depth=dot(to_pawn, forward),
                target_in_front_of_pawn=dot(to_target, forward) > dot(to_pawn, forward))


def run(owner, live=False):
    """Console entry: probe the equipped weapon and write one JSON report."""
    pc, pawn, manager = owner._get_runtime()
    if pc is None or pawn is None or manager is None:
        raise RuntimeError('Load into gameplay first')
    weapon = manager.CameraModeInputs.Weapon
    if weapon is None:
        raise RuntimeError('Equip a weapon first')
    base = int(owner._kernel32.GetModuleHandleW(None) or 0)
    if not base:
        raise RuntimeError('Main module unavailable')
    runtime = dict(pawn=int(pawn._get_address()), controller=int(pc._get_address()),
                   manager=int(manager._get_address()))
    report = probe(owner._native_read, base, weapon, manager, runtime)
    if live:
        try:
            report['live_aim'] = live_aim(owner._native_read, base, report, runtime['manager'], pawn)
        except Exception as exc:
            report['live_aim'] = dict(error=repr(exc)[:300])
    path = write(owner.SETTINGS_DIR, report)
    return report, path


def dump(read, base, rvas, length):
    """Read-only code windows at explicit RVAs (follow-up rounds, no new build)."""
    identity = parse_pe_identity(read, base)
    if identity != REVIEWED_BUILD:
        raise RuntimeError('Build differs from the reviewed build; no code read')
    if not 0 < length <= MAX_DUMP or not 0 < len(rvas) <= 32:
        raise RuntimeError('Dump request outside bounds')
    image = Image(read, base)
    windows = {}
    for rva in rvas:
        if image.code_rva(base + rva) is None:
            windows[hex(rva)] = dict(error='not inside an executable section')
            continue
        code = image.code(rva, length)
        windows[hex(rva)] = dict(hex=code.hex(), camera_cache_reads=anchors(code),
                                 calls=[dict(kind=k, at=o, target=hex(t))
                                        for k, o, t in scan_calls(code, rva, image)[:256]])
    return dict(version=VERSION, kind='code_dump', utc=datetime.now(timezone.utc).isoformat(),
                build=[hex(v) for v in identity], length=length, windows=windows,
                fire=dict(cls='dump'))


def run_dump(owner, rvas, length):
    base = int(owner._kernel32.GetModuleHandleW(None) or 0)
    if not base:
        raise RuntimeError('Main module unavailable')
    report = dump(owner._native_read, base, rvas, length)
    return report, write(owner.SETTINGS_DIR, report)
