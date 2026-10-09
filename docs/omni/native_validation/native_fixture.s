.intel_syntax noprefix
.text
.global run_stub
.type run_stub,@function
run_stub:
 mov rcx, rsi
 call rdi
.global fixture_return
fixture_return:
 ret
.section .note.GNU-stack,"",@progbits
