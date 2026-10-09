"""Assembly source of native_beam_origin.TEMPLATE (0.3.9.12, beam query depth).

Offline tool (keystone-engine + capstone): ``python docs/beam_origin_stub_source.py``
prints the template hex and its SHA-256. The shipped template must equal
``assemble()``; tests/test_beam_depth_0_3_9_12.py checks it when keystone exists.

Unchanged from the 0.3.8 FireBeam origin stub: entry counters, receiver vtable,
weapon, mode 5, flag 0x310 bit 2, weapon -> pawn -> controller -> manager chain,
TPS camera definition, the first 64 records and the replayed prologue.

New: the written query origin is the camera-cache position moved along the
camera-cache view direction to character depth plus margin (the 0.3.9.9 aim
trace rule), read from the aim-trace control block:
    d = (cos p cos y, cos p sin y, sin p)        p, y from POV.Rotation (degrees)
    depth = (Pawn - Camera) . d + beam_margin      (control +0xB0)
    origin = Camera + d * depth   only if control enabled and 0 < depth < max
Otherwise the camera-cache position is written as before.

Sentinels: 1111 buffer, 2222 receiver table, 3333 weapon, 4444 resume,
5555 aim control block, 6666 manager offset of POV.Rotation.
Scratch: rax, r10, r11, rflags (saved/restored), xmm0/xmm1 (saved/restored),
x87 (empty on entry and exit). Stack locals below the saved registers.
"""
import hashlib
import struct

ASM = """
pushfq
push rax
push r10
push r11
movabs r10, 0x1111111111111111
lock inc qword ptr [r10 + 8]
movabs r11, 0x2222222222222222
cmp qword ptr [rcx], r11
jne done
lock inc qword ptr [r10 + 0x10]
movabs r11, 0x3333333333333333
cmp qword ptr [rcx + 0xc8], r11
jne done
cmp word ptr [rcx + 0x2ea], 5
jne done
test byte ptr [rcx + 0x310], 4
jne done
mov r11, qword ptr [r11 + 0x1b0]
test r11, r11
je done
mov r11, qword ptr [r11 + 0x3c0]
test r11, r11
je done
mov r11, qword ptr [r11 + 0x2500]
test r11, r11
je done
mov rax, qword ptr [r11 + 0x3a48]
test rax, rax
je done
mov rax, qword ptr [rax + 0x10]
test rax, rax
je done
test byte ptr [rax + 0x1c], 2
jne done
sub rsp, 0x60
movdqu xmmword ptr [rsp], xmm0
movdqu xmmword ptr [rsp + 0x10], xmm1
mov rax, qword ptr [r11 + 0x1910]
mov qword ptr [rsp + 0x20], rax
mov rax, qword ptr [r11 + 0x1918]
mov qword ptr [rsp + 0x28], rax
mov rax, qword ptr [r11 + 0x1920]
mov qword ptr [rsp + 0x30], rax
xorpd xmm0, xmm0
mov qword ptr [rsp + 0x58], 0
movabs rax, 0x5555555555555555
cmp qword ptr [rax], 1
jne origin_ready
movabs rax, 0x6666666666666666
add rax, r11
movabs r10, 0x3f91df46a2529d39
mov qword ptr [rsp + 0x50], r10
fld qword ptr [rax]
fmul qword ptr [rsp + 0x50]
fsincos
fld qword ptr [rax + 8]
fmul qword ptr [rsp + 0x50]
fsincos
fmul st(0), st(2)
fstp qword ptr [rsp + 0x38]
fmulp st(1), st(0)
fstp qword ptr [rsp + 0x40]
fstp qword ptr [rsp + 0x48]
movabs rax, 0x5555555555555555
movsd xmm0, qword ptr [rax + 0x20]
subsd xmm0, qword ptr [rsp + 0x20]
mulsd xmm0, qword ptr [rsp + 0x38]
movsd xmm1, qword ptr [rax + 0x28]
subsd xmm1, qword ptr [rsp + 0x28]
mulsd xmm1, qword ptr [rsp + 0x40]
addsd xmm0, xmm1
movsd xmm1, qword ptr [rax + 0x30]
subsd xmm1, qword ptr [rsp + 0x30]
mulsd xmm1, qword ptr [rsp + 0x48]
addsd xmm0, xmm1
addsd xmm0, qword ptr [rax + 0xb0]
mov qword ptr [rsp + 0x58], 2
xorpd xmm1, xmm1
ucomisd xmm0, xmm1
jbe origin_ready
ucomisd xmm0, qword ptr [rax + 0x58]
jae origin_ready
movsd xmm1, qword ptr [rsp + 0x38]
mulsd xmm1, xmm0
addsd xmm1, qword ptr [rsp + 0x20]
movsd qword ptr [rsp + 0x20], xmm1
movsd xmm1, qword ptr [rsp + 0x40]
mulsd xmm1, xmm0
addsd xmm1, qword ptr [rsp + 0x28]
movsd qword ptr [rsp + 0x28], xmm1
movsd xmm1, qword ptr [rsp + 0x48]
mulsd xmm1, xmm0
addsd xmm1, qword ptr [rsp + 0x30]
movsd qword ptr [rsp + 0x30], xmm1
mov qword ptr [rsp + 0x58], 1
origin_ready:
movabs r10, 0x1111111111111111
mov rax, qword ptr [rsp + 0x58]
lock inc qword ptr [r10 + rax*8 + 0x4100]
movsd qword ptr [r10 + 0x4118], xmm0
mov rax, qword ptr [r11 + 0x1910]
mov qword ptr [r10 + 0x4120], rax
mov rax, qword ptr [r11 + 0x1918]
mov qword ptr [r10 + 0x4128], rax
mov rax, qword ptr [r11 + 0x1920]
mov qword ptr [r10 + 0x4130], rax
mov rax, qword ptr [rsp + 0x20]
mov qword ptr [r10 + 0x4138], rax
mov rax, qword ptr [rsp + 0x28]
mov qword ptr [r10 + 0x4140], rax
mov rax, qword ptr [rsp + 0x30]
mov qword ptr [r10 + 0x4148], rax
mov eax, 1
lock xadd qword ptr [r10], rax
cmp rax, 0x40
jae write_only
shl rax, 8
lea r10, [r10 + rax + 0x20]
shr rax, 8
inc rax
mov qword ptr [r10 + 0xf8], rax
mov qword ptr [r10 + 8], rcx
mov rax, qword ptr [rcx + 0xc8]
mov qword ptr [r10 + 0x10], rax
mov qword ptr [r10 + 0x18], r11
movzx eax, word ptr [rcx + 0x2ea]
mov dword ptr [r10 + 0x20], eax
movzx eax, word ptr [rcx + 0x310]
mov dword ptr [r10 + 0x24], eax
mov rax, qword ptr [rcx + 0x388]
mov qword ptr [r10 + 0x30], rax
mov rax, qword ptr [rcx + 0x390]
mov qword ptr [r10 + 0x38], rax
mov rax, qword ptr [rcx + 0x398]
mov qword ptr [r10 + 0x40], rax
mov rax, qword ptr [rcx + 0x3a0]
mov qword ptr [r10 + 0x60], rax
mov rax, qword ptr [rcx + 0x3a8]
mov qword ptr [r10 + 0x68], rax
mov rax, qword ptr [rcx + 0x3b0]
mov qword ptr [r10 + 0x70], rax
mov rax, qword ptr [rcx + 0x440]
mov qword ptr [r10 + 0x78], rax
mov rax, qword ptr [rcx + 0x448]
mov qword ptr [r10 + 0x80], rax
mov rax, qword ptr [rcx + 0x450]
mov qword ptr [r10 + 0x88], rax
mov rax, qword ptr [rcx + 0x3b8]
mov qword ptr [r10 + 0x90], rax
mov rax, qword ptr [rcx + 0x3c0]
mov qword ptr [r10 + 0x98], rax
mov rax, qword ptr [rcx + 0x3c8]
mov qword ptr [r10 + 0xa0], rax
mov rax, qword ptr [rsp + 0x20]
mov qword ptr [rcx + 0x388], rax
mov qword ptr [r10 + 0x48], rax
mov rax, qword ptr [rsp + 0x28]
mov qword ptr [rcx + 0x390], rax
mov qword ptr [r10 + 0x50], rax
mov rax, qword ptr [rsp + 0x30]
mov qword ptr [rcx + 0x398], rax
mov qword ptr [r10 + 0x58], rax
mov rax, qword ptr [r11 + 0x1910]
mov qword ptr [r10 + 0xa8], rax
mov rax, qword ptr [r11 + 0x1918]
mov qword ptr [r10 + 0xb0], rax
mov rax, qword ptr [r11 + 0x1920]
mov qword ptr [r10 + 0xb8], rax
movsd qword ptr [r10 + 0xc0], xmm0
mov rax, qword ptr [rsp + 0x58]
mov qword ptr [r10 + 0xc8], rax
mov rax, qword ptr [r10 + 0xf8]
mov qword ptr [r10], rax
jmp restore_locals
write_only:
mov rax, qword ptr [rsp + 0x20]
mov qword ptr [rcx + 0x388], rax
mov rax, qword ptr [rsp + 0x28]
mov qword ptr [rcx + 0x390], rax
mov rax, qword ptr [rsp + 0x30]
mov qword ptr [rcx + 0x398], rax
restore_locals:
movdqu xmm0, xmmword ptr [rsp]
movdqu xmm1, xmmword ptr [rsp + 0x10]
add rsp, 0x60
done:
pop r11
pop r10
pop rax
popfq
push r15
push r14
push rsi
push rdi
push rbx
sub rsp, 0x190
"""

RESUME_SENTINEL = 0x4444444444444444


def assemble() -> bytes:
    import keystone

    encoded, _ = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64).asm(ASM, 0)
    return bytes(encoded) + b'\xff\x25\x00\x00\x00\x00' + struct.pack('<Q', RESUME_SENTINEL)


if __name__ == '__main__':
    import capstone

    code = assemble()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for ins in md.disasm(code[:-8], 0):
        print(f'{ins.address:4x}: {ins.mnemonic} {ins.op_str}')
    print(len(code), hashlib.sha256(code).hexdigest())
    print(code.hex())
