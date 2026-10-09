# Assembly source of native_aim_origin.STUB (0.3.9.9, trace-start depth). keystone-engine; offline tool.
import keystone, hashlib, struct, capstone
ASM = """
movabs r10, 0x1122334455667701
cmp qword ptr [r10], 1
jne replay
lock inc qword ptr [r10+0x08]
cmp rbx, qword ptr [r10+0x10]
jne mismatch
movsd xmm0, qword ptr [rsp+0x140]
subsd xmm0, qword ptr [rsp+0x170]
movsd xmm1, qword ptr [rsp+0x148]
subsd xmm1, qword ptr [rsp+0x178]
movsd xmm2, qword ptr [rsp+0x150]
subsd xmm2, qword ptr [rsp+0x180]
movapd xmm3, xmm0
mulsd xmm3, xmm3
movapd xmm4, xmm1
mulsd xmm4, xmm4
addsd xmm3, xmm4
movapd xmm4, xmm2
mulsd xmm4, xmm4
addsd xmm3, xmm4
sqrtsd xmm3, xmm3
ucomisd xmm3, qword ptr [r10+0xa8]
jp skip
jbe skip
divsd xmm0, xmm3
divsd xmm1, xmm3
divsd xmm2, xmm3
movsd xmm4, qword ptr [r10+0x20]
subsd xmm4, qword ptr [rsp+0x170]
mulsd xmm4, xmm0
movsd xmm5, qword ptr [r10+0x28]
subsd xmm5, qword ptr [rsp+0x178]
mulsd xmm5, xmm1
addsd xmm4, xmm5
movsd xmm5, qword ptr [r10+0x30]
subsd xmm5, qword ptr [rsp+0x180]
mulsd xmm5, xmm2
addsd xmm4, xmm5
addsd xmm4, qword ptr [r10+0x50]
movsd qword ptr [r10+0xa0], xmm4
xorpd xmm5, xmm5
ucomisd xmm4, xmm5
jp skip
jbe skip
ucomisd xmm4, qword ptr [r10+0x58]
jp skip
jae skip
ucomisd xmm4, xmm3
jae skip
mov r11, qword ptr [rsp+0x170]
mov qword ptr [r10+0x70], r11
mov r11, qword ptr [rsp+0x178]
mov qword ptr [r10+0x78], r11
mov r11, qword ptr [rsp+0x180]
mov qword ptr [r10+0x80], r11
mulsd xmm0, xmm4
addsd xmm0, qword ptr [rsp+0x170]
movsd qword ptr [rsp+0x170], xmm0
movsd qword ptr [r10+0x88], xmm0
mulsd xmm1, xmm4
addsd xmm1, qword ptr [rsp+0x178]
movsd qword ptr [rsp+0x178], xmm1
movsd qword ptr [r10+0x90], xmm1
mulsd xmm2, xmm4
addsd xmm2, qword ptr [rsp+0x180]
movsd qword ptr [rsp+0x180], xmm2
movsd qword ptr [r10+0x98], xmm2
lock inc qword ptr [r10+0x18]
jmp replay
mismatch:
lock inc qword ptr [r10+0x68]
jmp replay
skip:
lock inc qword ptr [r10+0x60]
replay:
lea r8, [rsp+0x170]
lea r9, [rsp+0x140]
"""
if __name__ == '__main__':
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
    enc, _ = ks.asm(ASM, 0)
    body = bytes(enc) + b'\xff\x25\x00\x00\x00\x00' + struct.pack('<Q', 0x1122334455667702)
    print(len(body)); print(body.hex()); print(hashlib.sha256(body).hexdigest())
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    for ins in md.disasm(body, 0):
        print(f'{ins.address:#05x} {ins.mnemonic} {ins.op_str}')
