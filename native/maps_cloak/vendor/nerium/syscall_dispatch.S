#include <asm/unistd.h>

.text
.hidden device_lab_original_syscall
.hidden device_lab_sys_uname
.hidden device_lab_sys_fstatfs
.hidden device_lab_sys_readlinkat
.hidden device_lab_sys_openat
.global device_lab_syscall_entry
.hidden device_lab_syscall_entry
.type device_lab_syscall_entry, @function
device_lab_syscall_entry:
    cmp $__NR_uname, %rdi
    je .Luname
    cmp $__NR_fstatfs, %rdi
    je .Lfstatfs
    cmp $__NR_readlinkat, %rdi
    je .Lreadlinkat
    cmp $__NR_openat, %rdi
    je .Lopenat
    // Tail forwarding preserves every register and stack argument of the variadic API.
    jmp *device_lab_original_syscall(%rip)
.Luname:
    mov %rsi, %rdi
    jmp device_lab_sys_uname
.Lfstatfs:
    mov %rsi, %rdi
    mov %rdx, %rsi
    jmp device_lab_sys_fstatfs
.Lreadlinkat:
    mov %rsi, %rdi
    mov %rdx, %rsi
    mov %rcx, %rdx
    mov %r8, %rcx
    jmp device_lab_sys_readlinkat
.Lopenat:
    mov %rsi, %rdi
    mov %rdx, %rsi
    mov %rcx, %rdx
    mov %r8, %rcx
    jmp device_lab_sys_openat
.size device_lab_syscall_entry, .-device_lab_syscall_entry
.section .note.GNU-stack,"",@progbits
