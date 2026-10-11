.intel_syntax noprefix
.text
# Inline prefix at the already reviewed AimOffset entry. No calls, new RVA,
# UObject dereferences or worker-thread Python. RDX is the caller-owned vector.
# control: mode, exact node, exact caller, overrides, dispatches, packed ff.
# mode 1 retains .32's yaw-only neutralisation; mode 2 uses packed yaw/alpha.
pushfq
push rax
push r10
movabs r10, 0x1111111111111111
cmp rcx, [r10+8]
jne done
mov rax, [rsp+24]
cmp rax, [r10+16]
jne done
test rdx, rdx
je done
lock inc qword ptr [r10+32]
cmp qword ptr [r10], 1
je legacy
cmp qword ptr [r10], 2
jne done
sub rsp, 64
movdqu [rsp], xmm0
movdqu [rsp+16], xmm1
movdqu [rsp+32], xmm2
stmxcsr [rsp+48]
mov eax, [rsp+48]
or eax, 0x1f80
mov [rsp+52], eax
ldmxcsr [rsp+52]
# One aligned 64-bit load: yaw and alpha cannot come from different updates.
mov rax, [r10+40]
movd xmm0, eax
cvtss2sd xmm0, xmm0
shr rax, 32
movd xmm1, eax
cvtss2sd xmm1, xmm1
# Reject corrupted publications and invalid original pitch without writing.
ucomisd xmm0, xmm0
jp restore
ucomisd xmm0, [rip+max_yaw]
ja restore
ucomisd xmm0, [rip+min_yaw]
jb restore
ucomisd xmm1, xmm1
jp restore
ucomisd xmm1, [rip+one]
ja restore
ucomisd xmm1, [rip+zero]
jb restore
movsd xmm2, [rdx+8]
ucomisd xmm2, xmm2
jp restore
ucomisd xmm2, [rip+max_pitch]
ja restore
ucomisd xmm2, [rip+min_pitch]
jb restore
mulsd xmm2, xmm1
movsd [rdx], xmm0
movsd [rdx+8], xmm2
lock inc qword ptr [r10+24]
restore:
ldmxcsr [rsp+48]
movdqu xmm0, [rsp]
movdqu xmm1, [rsp+16]
movdqu xmm2, [rsp+32]
add rsp, 64
jmp done
legacy:
mov qword ptr [rdx], 0
lock inc qword ptr [r10+24]
done:
pop r10
pop rax
popfq
jmp end
# RIP-relative constants belong to each prefix copy, not game memory.
max_yaw: .double 35.0
min_yaw: .double -35.0
one: .double 1.0
zero: .double 0.0
max_pitch: .double 180.0
min_pitch: .double -180.0
end:
.section .note.GNU-stack,"",@progbits
