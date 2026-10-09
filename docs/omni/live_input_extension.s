.intel_syntax noprefix
.text
.global code
code:
.incbin "vector_original.bin", 0, 0xd0
jne live_input
.incbin "vector_original.bin", 0xd6
.set record_done, code + 0x180
.set record_changed, code + 0x174
live_input:
 cmp qword ptr [r10+96], 4
 jne record_done
 cmp byte ptr [rcx+0x1100], 3
 jne record_done
 test byte ptr [rcx+0x4458], 1
 jz record_done
 movzx eax, byte ptr [rcx+0x4448]
 cmp eax, 3
 ja record_done
 mov r11, qword ptr [rcx+0x4430]
 cmp r11, qword ptr [r10+112]
 jne record_done
 test r11, r11
 jz record_done
 mov r9, rax
 shl r9, 5
 lea r9, [r10+r9+320]
 mov eax, dword ptr [r11+rax*4+144]
 cmp eax, dword ptr [r9]
 jne record_done
 sub rsp, 96
 movdqu [rsp], xmm0
 movdqu [rsp+16], xmm1
 movdqu [rsp+32], xmm2
 movdqu [rsp+48], xmm3
 movdqu [rsp+64], xmm4
 movdqu [rsp+80], xmm5
 mov r11, qword ptr [r10+256]
 mov qword ptr [r10+312], 1
read_vector:
 cmp r11, 0x10000
 jb rejected
 mov rax, qword ptr [r11]
 shl rax, 1
 movabs r9, 0x8060000000000000
 cmp rax, r9
 ja rejected
 mov rax, qword ptr [r11+8]
 shl rax, 1
 cmp rax, r9
 ja rejected
 movsd xmm0, [r11]
 movsd xmm1, [r11+8]
 movapd xmm2, xmm0
 mulsd xmm2, xmm0
 movapd xmm3, xmm1
 mulsd xmm3, xmm1
 addsd xmm2, xmm3
 ucomisd xmm2, [r10+272]
 jbe try_last
 sqrtsd xmm2, xmm2
 divsd xmm0, xmm2
 divsd xmm1, xmm2
 movsd [r10+280], xmm0
 movsd [r10+288], xmm1
 mov qword ptr [r10+296], 0
 movzx eax, byte ptr [rcx+0x4448]
 mov [r10+304], rax
 shl rax, 5
 lea r9, [r10+rax+320]
 movsd xmm2, [r9+8]
 movsd xmm3, [r9+16]
 movapd xmm4, xmm0
 mulsd xmm4, xmm2
 movapd xmm5, xmm1
 mulsd xmm5, xmm3
 addsd xmm4, xmm5
 mulsd xmm1, xmm2
 mulsd xmm0, xmm3
 subsd xmm1, xmm0
 movsd [rdx], xmm4
 movsd [rdx+8], xmm1
 mov qword ptr [rdx+16], 0
 movdqu xmm0, [rsp]
 movdqu xmm1, [rsp+16]
 movdqu xmm2, [rsp+32]
 movdqu xmm3, [rsp+48]
 movdqu xmm4, [rsp+64]
 movdqu xmm5, [rsp+80]
 add rsp, 96
 jmp record_changed
try_last:
 cmp qword ptr [r10+312], 1
 jne rejected
 mov qword ptr [r10+312], 2
 mov r11, qword ptr [r10+264]
 jmp read_vector
rejected:
 movdqu xmm0, [rsp]
 movdqu xmm1, [rsp+16]
 movdqu xmm2, [rsp+32]
 movdqu xmm3, [rsp+48]
 movdqu xmm4, [rsp+64]
 movdqu xmm5, [rsp+80]
 add rsp, 96
 jmp record_done
