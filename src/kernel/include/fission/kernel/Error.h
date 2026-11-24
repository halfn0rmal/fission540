#pragma once

#include <stdexcept>
#include <string>

namespace fission::kernel {

class KernelError : public std::runtime_error {
public:
    explicit KernelError(const std::string& what) : std::runtime_error(what) {}
};

} // namespace fission::kernel
