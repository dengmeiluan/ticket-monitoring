#pragma once

#include <string>

using DeviceLabSyscall = long (*)(long, ...);
void configure_proc_views(const std::string& cpu_path, const std::string& module_path, DeviceLabSyscall syscall);
int proc_view_fd(int directory, const char* path, int flags);
const char* proc_descriptor_path(int fd);
std::string proc_view_controls();
