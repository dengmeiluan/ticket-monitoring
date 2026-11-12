#pragma once
#include <linux/seccomp.h>
#include <cstddef>
#include <cstdint>

bool notification_valid(int listener, uint64_t id);
int write_notification_memory(const seccomp_notif& request, int listener, uint64_t address, const void* data, size_t size);
// 0: continue in kernel; 1: response prepared; 2: atomically answered by ADDFD.
int handle_proc_notification(const seccomp_notif& request, seccomp_notif_resp& response, int listener);
