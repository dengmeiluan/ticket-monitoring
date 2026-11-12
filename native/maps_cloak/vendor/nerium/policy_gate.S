.text
.hidden device_lab_policy_prctl
.hidden device_lab_install_policy
.global device_lab_policy_entry
.hidden device_lab_policy_entry
.type device_lab_policy_entry,@function
device_lab_policy_entry:
    cmpl $22, %edi
    jne .Lpolicy_forward
    cmpq $2, %rsi
    jne .Lpolicy_forward
    jmp device_lab_install_policy
.Lpolicy_forward:
    jmp *device_lab_policy_prctl(%rip)
.size device_lab_policy_entry,.-device_lab_policy_entry
.section .note.GNU-stack,"",@progbits
