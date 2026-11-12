#pragma once
#include <string>
namespace zygisk { struct Api; }
bool install_openat2_policy(zygisk::Api* api);
bool restore_openat2_policy(zygisk::Api* api);
void save_openat2_policy(const std::string& directory);
