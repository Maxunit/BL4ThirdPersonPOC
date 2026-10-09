"""Tested rear regular-blocker filter; bounded source queries and original-hit retention.
Native bytes match the successful gameplay probe. Work buffers share the retained
collision owner allocation. No Python observer, hotkey or extra hook is installed.
"""
import hashlib
import struct

FULL_STRIDE = 8704
AUX_HEADER = 512
INSERT_OFFSET = 480
DISPLACED = bytes.fromhex('488b95a0010000')
FULL_STUB = bytes.fromhex('9c5051525657415041514152415349bb8877665544332211f049ff038b8da801000085c90f8e1601000081f9000100000f8f0a0100003b8dac0100000f8ffe000000488bb5a00100004881fe000001000f82ea00000048b800000000008000004839c60f83d7000000b801000000f0490fc143084883f8400f83c20000004c8d50014869c0002200004d8d8c030002000049c7010000000049895908488b83c800000049894110488b85a801000049894118498971200fb645f04189412883f9207e05b920000000418949304189c84c89cf4883c740488b7570b903000000fcf348a5488db388030000b903000000f348a5488db3a0030000b903000000f348a5488db3b8030000b903000000f348a5488b8590000000498981a0000000488bb5a0010000498db9000200004489c1c1e105f348a54d89114c89d2f049ff4310415b415a415941585f5e5a59589d')
FULL_STUB_HASH = '5e4f360775d451e8b38221930c5b52d877b4f7b2b93d9311ddd37090a06b1c03'
GUARDS = ((142, '0f85dd0f0000', 'receiver_class'), (170, '0f85c10f0000', 'weapon_identity'), (183, '0f85b40f0000', 'receiver_mode'), (196, '0f85a70f0000', 'receiver_flag_10'), (209, '0f859a0f0000', 'query_tag'), (222, '0f858d0f0000', 'query_shape'), (238, '0f857d0f0000', 'query_radius'), (258, '0f85690f0000', 'start_matches_origin_x'), (275, '0f85580f0000', 'start_matches_origin_y'), (292, '0f85470f0000', 'start_matches_origin_z'), (315, '0f84300f0000', 'controller_missing'), (331, '0f84200f0000', 'pawn_missing'), (347, '0f84100f0000', 'manager_missing'), (363, '0f85000f0000', 'camera_origin_x'), (380, '0f85ef0e0000', 'camera_origin_y'), (397, '0f85de0e0000', 'camera_origin_z'), (413, '0f84ce0e0000', 'runtime_missing'), (426, '0f84c10e0000', 'definition_missing'), (436, '0f85b70e0000', 'first_person'), (450, '0f8ea90e0000', 'empty_or_negative_list'), (462, '0f8f9d0e0000', 'list_over_256'), (474, '0f8f910e0000', 'count_over_capacity'), (490, '0f84810e0000', 'null_hit_array'), (522, 'e9620e0000', 'no_blocking_penetrating_hit'), (539, '0f85500e0000', 'correction_busy'))

def extend_prefilter(blob: bytes, auxiliary: int) -> bytes:
    """Capture before the original penetrating-hit filter; count early exits.

    Branch conditions and their original exit target stay semantically intact.
    Appended counter stubs preserve RAX/RFLAGS. The capture stub restores every
    touched register/flag and executes the displaced load before returning.
    No query or geometry decision is changed; diagnostic buffers stay pinned.
    """
    if len(blob) != 4416 or blob[INSERT_OFFSET:INSERT_OFFSET + len(DISPLACED)] != DISPLACED:
        raise RuntimeError('Prefilter insertion boundary differs')
    if hashlib.sha256(FULL_STUB).hexdigest() != FULL_STUB_HASH:
        raise RuntimeError('Prefilter recorder fingerprint differs')
    sentinel = struct.pack('<Q', 1234605616436508552)
    if FULL_STUB.count(sentinel) != 1 or not 65536 <= auxiliary < 140737488355328:
        raise RuntimeError('Auxiliary relocation invalid')
    result = bytearray(blob)
    result[INSERT_OFFSET:INSERT_OFFSET + len(DISPLACED)] = b'\xe9' + struct.pack('<i', len(blob) - (INSERT_OFFSET + 5)) + b'\x90' * (len(DISPLACED) - 5)
    result.extend(FULL_STUB.replace(sentinel, struct.pack('<Q', auxiliary)))
    result.extend(DISPLACED)
    result.extend(b'\xe9' + struct.pack('<i', INSERT_OFFSET + len(DISPLACED) - (len(result) + 5)))
    for index, (offset, expected, label) in enumerate(GUARDS):
        expected = bytes.fromhex(expected)
        if blob[offset:offset + len(expected)] != expected:
            raise RuntimeError(f'Guard branch differs: {label}')
        displacement_offset = offset + (1 if expected[0] == 233 else 2)
        old_target = offset + len(expected) + struct.unpack_from('<i', blob, displacement_offset)[0]
        if old_target != 4209:
            raise RuntimeError('Guard exit target differs')
        destination = len(result)
        struct.pack_into('<i', result, displacement_offset, destination - (offset + len(expected)))
        result.extend(b'\x9cPH\xb8' + struct.pack('<Q', auxiliary) + bytes.fromhex('f048ff80') + struct.pack('<I', 64 + index * 8) + b'X\x9d')
        result.extend(b'\xe9' + struct.pack('<i', old_target - (len(result) + 5)))
    if len(result) > 8192:
        raise RuntimeError('Extended recorder exceeds owned code allocation')
    return bytes(result)

def extend_regular_recorder(blob: bytes, auxiliary: int) -> bytes:
    """Add query-only continuation for the no-penetrating-blocker route.

    Original penetrating cases keep their production decisions. New regular
    cases use the same query ABI and origin/direction/range guards, but return
    through broad-array release before every original-array rewrite. A private
    unused qword in the stub's existing stack frame separates the routes.
    """
    result = bytearray(extend_prefilter(blob, auxiliary))

    def jump(target: int) -> bytes:
        return b'\xe9' + struct.pack('<i', target - (len(result) + 5))

    def splice(offset: int, expected: str, body: bytes, return_to: int | None) -> int:
        original = bytes.fromhex(expected)
        if blob[offset:offset + len(original)] != original:
            raise RuntimeError(f'Query-only insertion differs at {offset:#x}')
        destination = len(result)
        result.extend(body)
        if return_to is not None:
            result.extend(jump(return_to))
        result[offset:offset + len(original)] = b'\xe9' + struct.pack('<i', destination - (offset + 5)) + b'\x90' * (len(original) - 5)
        return destination
    splice(90, '48c78424d800000000000000', bytes.fromhex('48c78424f80000000000000048c78424d800000000000000'), 102)
    flag_entry = len(result)
    result.extend(bytes.fromhex('48c78424f800000001000000'))
    result.extend(jump(527))
    offset, expected, label = next((g for g in GUARDS if g[2] == 'no_blocking_penetrating_hit'))
    counter = offset + 5 + struct.unpack_from('<i', result, offset + 1)[0]
    if result[counter + 22] != 233:
        raise RuntimeError('No-penetrating counter return differs')
    struct.pack_into('<i', result, counter + 23, flag_entry - (counter + 27))
    splice(739, '4c89a7f8000000', bytes.fromhex('4c89a7f8000000488b8424f8000000488987e001000048c787e801000000000000'), 746)

    def route_gate(offset: int, expected: str, diagnostic: bytes, diagnostic_target: int, normal: bytes, normal_target: int) -> None:
        start = len(result)
        check = bytes.fromhex('9c4883bc240001000001')
        branch = b'\x0f\x85' + struct.pack('<i', len(diagnostic) + 1 + 5)
        result.extend(check + branch + b'\x9d' + diagnostic)
        result.extend(jump(diagnostic_target))
        result.extend(b'\x9d' + normal)
        result.extend(jump(normal_target))
        original = bytes.fromhex(expected)
        if blob[offset:offset + len(original)] != original:
            raise RuntimeError(f'Query-only route differs at {offset:#x}')
        result[offset:offset + len(original)] = b'\xe9' + struct.pack('<i', start - (offset + 5)) + b'\x90' * (len(original) - 5)
    narrow_entry = len(result)
    check = bytes.fromhex('9c4883bc240001000001')
    result.extend(check)
    jne = len(result)
    result.extend(b'\x0f\x85' + b'\x00' * 4)
    result.extend(bytes.fromhex('48837c246800'))
    jnonnull = len(result)
    result.extend(b'\x0f\x85' + b'\x00' * 4)
    result.extend(b'\x9d')
    result.extend(jump(1319))
    normal = len(result)
    struct.pack_into('<i', result, jne + 2, normal - (jne + 6))
    struct.pack_into('<i', result, jnonnull + 2, normal - (jnonnull + 6))
    result.extend(b'\x9d' + bytes.fromhex('488b4c2460'))
    result.extend(jump(1304))
    if blob[1299:1304] != bytes.fromhex('488b4c2460'):
        raise RuntimeError('Narrow release load differs')
    result[1299:1304] = b'\xe9' + struct.pack('<i', narrow_entry - (1299 + 5))
    gate_start = len(result)
    normal_cmp = bytes.fromhex('837f3c01')
    diag = bytes.fromhex('f20f118718010000')
    normal_start = gate_start + 10 + 6 + 1 + len(diag) + 5 + 1
    normal_cmp += b'\x0f\x85' + struct.pack('<i', 4199 - (normal_start + 10))
    route_gate(1461, '837f3c010f85a80a0000', diag, 1621, normal_cmp, 1471)
    route_gate(1835, '83bfcc00000001', b'', 1971, bytes.fromhex('83bfcc00000001'), 1842)
    route_gate(2306, '83bf3c01000000', bytes.fromhex('c787e801000001000000c78740010000d1000000'), 4183, bytes.fromhex('83bf3c01000000'), 2313)
    if len(result) > 8192:
        raise RuntimeError('Query-only recorder exceeds owned code allocation')
    return bytes(result)

def extend_source_recorder(blob: bytes, auxiliary: int) -> bytes:
    """Replace only diagnostic query starts with the captured receiver source.

    Normal production queries and penetrating-hit adoption retain their bytes.
    New query arguments use the stable per-call record, with finite coordinates
    and a bounded camera/source offset checked before the first source query.
    Both radii use the original endpoint, with no +20 offset at the source.
    """
    result = bytearray(extend_regular_recorder(blob, auxiliary))

    def jump(target: int) -> bytes:
        return b'\xe9' + struct.pack('<i', target - (len(result) + 5))

    def route(offset: int, expected: str, diagnostic: bytes, return_to: int) -> None:
        original = bytes.fromhex(expected)
        if blob[offset:offset + len(original)] != original:
            raise RuntimeError(f'Weapon-source query boundary differs at {offset:#x}')
        start = len(result)
        result.extend(bytes.fromhex('9c4883bc240001000001'))
        result.extend(b'\x0f\x85' + struct.pack('<i', 1 + len(diagnostic) + 5))
        result.extend(b'\x9d' + diagnostic)
        result.extend(jump(return_to))
        result.extend(b'\x9d' + original)
        result.extend(jump(return_to))
        result[offset:offset + len(original)] = b'\xe9' + struct.pack('<i', start - (offset + 5)) + b'\x90' * (len(original) - 5)
    tag = 739 + 5 + struct.unpack_from('<i', result, 739 + 1)[0]
    tag_return = tag + len(bytes.fromhex('4c89a7f8000000488b8424f8000000488987e001000048c787e801000000000000'))
    if result[tag_return] != 233:
        raise RuntimeError('Diagnostic marker initializer differs')
    marker_start = len(result)
    result.extend(bytes.fromhex('48c787f00100000000000048c787f801000000000000'))
    result.extend(jump(746))
    struct.pack_into('<i', result, tag_return + 1, marker_start - (tag_return + 5))
    check = bytearray()
    failures = []
    for offset in (64, 72, 80, 88, 96, 104, 160, 168, 176):
        check.extend(bytes.fromhex('488b87') + struct.pack('<I', offset))
        check.extend(bytes.fromhex('48c1e83425ff0700003dff070000'))
        failures.append(len(check))
        check.extend(b'\x0f\x84' + b'\x00' * 4)
    check.extend(bytes.fromhex('660fefc9'))
    for source, camera in ((160, 64), (168, 72), (176, 80)):
        check.extend(bytes.fromhex('f20f1087') + struct.pack('<I', source))
        check.extend(bytes.fromhex('f20f5c87') + struct.pack('<I', camera))
        check.extend(bytes.fromhex('f20f59c0f20f58c8'))
    check.extend(b'H\xb8' + struct.pack('<d', 512.0 ** 2))
    check.extend(bytes.fromhex('66480f6ec0660f2ec8'))
    failures.append(len(check))
    check.extend(b'\x0f\x87' + b'\x00' * 4)
    failures.append(len(check))
    check.extend(b'\x0f\x8a' + b'\x00' * 4)
    check.extend(bytes.fromhex('4c8d87a00000004c8b8d9000000048c787f001000001000000'))
    success = len(check)
    check.extend(b'\xe9' + b'\x00' * 4)
    reject = len(check)
    check.extend(bytes.fromhex('c78740010000d2000000'))
    reject_jump = len(check)
    check.extend(b'\xe9' + b'\x00' * 4)
    body_start = len(result) + 17
    for offset in failures:
        struct.pack_into('<i', check, offset + 2, reject - (offset + 6))
    struct.pack_into('<i', check, success + 1, 1166 - (body_start + success + 5))
    struct.pack_into('<i', check, reject_jump + 1, 4199 - (body_start + reject_jump + 5))
    route(1155, '4c8b45704c8b8d90000000', bytes(check), 1166)
    broad = bytes.fromhex('4c8d87a000000048c787f801000001000000')
    for source, destination in ((160, 288), (168, 296), (176, 304)):
        broad += bytes.fromhex('488b87') + struct.pack('<I', source)
        broad += bytes.fromhex('488987') + struct.pack('<I', destination)
    route(2162, '4c8d8424e0000000', broad, 2170)
    finish = 2306 + 5 + struct.unpack_from('<i', result, 2306 + 1)[0]
    marker = bytes.fromhex('c78740010000d1000000')
    position = result.find(marker, finish, finish + 80)
    if position < 0:
        raise RuntimeError('Diagnostic completion marker differs')
    result[position:position + len(marker)] = bytes.fromhex('c78740010000d3000000')
    if len(result) > 8192:
        raise RuntimeError('Weapon-source recorder exceeds owned code allocation')
    return bytes(result)
REGULAR_FILTER = bytes.fromhex('c78740010000d4000000837f3c010f85980300008b4f3085c90f8e8d03000083f9200f8f840300003b4f380f857b0300003b8da80100000f85650300003b8dac0100000f8f59030000488b85a0010000483b87d00000000f8545030000837f28010f853b030000807df0010f853103000083bfcc000000010f852e03000083bf0c010000010f85210300008b8fc000000085c90f881303000083f9200f8f0a0300003b8fc80000000f85fe0200008b8f0001000085c90f88f002000083f9200f8fe70200003b8f080100000f85db020000c78740010000d5000000837f2c000f85c702000083bf10010000000f85ba0200008b8fc00000004c8d870022000085c9741941f680ad000000010f859b0200004981c000010000ffc975e78b8f000100004c8d870042000085c9741941f680ad000000010f85710200004981c000010000ffc975e7c78740010000d6000000f20f10a77801000048b8000000000000444066480f6ec0f20f5ce0660fefc0660f2ee00f8a330200000f862d0200008b4f304c8daf000200004531f641f685ad000000010f842401000041f685ad000000020f85040200004d85f60f85fb0100004983bdd8000000000f84ed0100004d89ee31d2498b441570483b4417400f85d801000083c20883fa3075e8418b4504250000807f3d0000807f0f84bc010000f3410f5a4504660fefc9660f2ec10f86a801000048b8000000000000f03f66480f6ec8660f2ec10f878f010000418b4508250000807f3d0000807f0f847b010000f3410f5a4508660fefc9660f2ec10f8267010000660f2ec40f835d01000041ba10000000660fefd231d24b8b44150048c1e83425ff0700003dff0700000f8438010000f2430f10441500f20f5c441740f20f59841788000000f20f58d04183c20883c20883fa1875c1660fefc0660f2ed00f8a040100000f86fe000000660f2ed40f83f40000004183fa2874974981c500010000ffc90f85bffeffff4d85f60f84d6000000c78740010000d70000008b4f30c1e1054c8d87000200004c8b8da0010000498b00493b010f85ac0000004983c0084983c108ffc975e8448b5f30488db700020000488b95a00100004531ff4c39f674274989f04989d1b920000000498b004989014983c0084983c108ffc975ee4881c20001000041ffc74881c60001000041ffcb75c84489bda8010000c645f000c7874401000001000000c78740010000d8000000c787d0010000010000004489bfd4010000c787d801000000000000488b8424d8000000f048ff4020eb0ac78740010000d7000000e944332211')
REGULAR_FILTER_HASH = 'd3d0c1cc42a59163c0c15bfc9f50cd79eb9e43abcb11f522ed394879a9d87800'

def extend_recorder(blob: bytes, auxiliary: int) -> bytes:
    """Enable the bounded B route after both stored-source queries are copied.

    Keep the production penetrating route. On the new regular route, remove
    exactly one rear blocker only when BOTH complete source queries are clear.
    All nonblocking original hits retain byte identity and original ordering.
    No new result adoption or synthetic hit; the native return flag becomes
    false only after the validated compacting operation has committed.
    """
    result = bytearray(extend_source_recorder(blob, auxiliary))
    if hashlib.sha256(REGULAR_FILTER).hexdigest() != REGULAR_FILTER_HASH:
        raise RuntimeError('Regular-blocker filter fingerprint differs')
    if REGULAR_FILTER[-5:] != bytes.fromhex('e944332211'):
        raise RuntimeError('Regular-blocker filter release relocation differs')

    def jump(target: int) -> bytes:
        return b'\xe9' + struct.pack('<i', target - (len(result) + 5))
    tag = 739 + 5 + struct.unpack_from('<i', result, 739 + 1)[0]
    tag_return = tag + len(bytes.fromhex('4c89a7f8000000488b8424f8000000488987e001000048c787e801000000000000'))
    marker = tag_return + 5 + struct.unpack_from('<i', result, tag_return + 1)[0]
    expected = bytes.fromhex('48c787f00100000000000048c787f801000000000000')
    if result[marker:marker + len(expected)] != expected or result[marker + len(expected)] != 233:
        raise RuntimeError('Source marker initialization differs')
    correction_init = len(result)
    result.extend(bytes.fromhex('48c787d00100000000000048c787d801000000000000'))
    result.extend(jump(746))
    old_jump = marker + len(expected)
    struct.pack_into('<i', result, old_jump + 1, correction_init - (old_jump + 5))
    gate = 2306 + 5 + struct.unpack_from('<i', result, 2306 + 1)[0]
    sequence = bytes.fromhex('c787e801000001000000c78740010000d3000000')
    finish = result.find(sequence, gate, gate + 80)
    if finish < 0 or result[finish + len(sequence)] != 233:
        raise RuntimeError('Source-only completion arm differs')
    branch = finish + len(sequence)
    if branch + 5 + struct.unpack_from('<i', result, branch + 1)[0] != 4183:
        raise RuntimeError('Source-only release target differs')
    filter_start = len(result)
    result.extend(REGULAR_FILTER)
    struct.pack_into('<i', result, len(result) - 4, 4183 - len(result))
    struct.pack_into('<i', result, branch + 1, filter_start - (branch + 5))
    if len(result) > 8192:
        raise RuntimeError('Regular-blocker A/B exceeds owned code allocation')
    return bytes(result)
