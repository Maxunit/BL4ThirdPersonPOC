.intel_syntax noprefix
.text
.global run_free_look
.type run_free_look,@function
# SysV wrapper for the Windows-register inline prefix, with exact caller label.
# rdi=stub, rsi=node, rdx=caller vector, rcx=128-byte state buffer.
run_free_look:
 mov r8, rcx
 mov rcx, rsi
 movdqu xmm0, [r8]
 movdqu xmm1, [r8+16]
 movdqu xmm2, [r8+32]
 movabs rax, 0x1234567812345678
 movabs r10, 0x8765432187654321
 mov [r8+88], rsp
 stmxcsr [r8+112]
 stc
 pushfq
 pop qword ptr [r8+96]
 call rdi
.global free_look_return
free_look_return:
 mov [r8+48], rax
 mov [r8+56], r10
 mov [r8+64], rcx
 mov [r8+72], rdx
 mov [r8+80], rsp
 pushfq
 pop qword ptr [r8+104]
 stmxcsr [r8+116]
 movdqu [r8], xmm0
 movdqu [r8+16], xmm1
 movdqu [r8+32], xmm2
 ret
.section .note.GNU-stack,"",@progbits
