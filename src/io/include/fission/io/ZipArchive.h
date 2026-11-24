#pragma once

#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace fission::io {

class IoError : public std::runtime_error {
public:
    explicit IoError(const std::string& what) : std::runtime_error(what) {}
};

// Minimal read-only ZIP reader. Supports Stored, Deflate and Zstandard (method 93),
// which newer Fusion 360 builds use and most zip libraries don't handle.
class ZipArchive {
public:
    struct Entry {
        std::string name;
        std::uint16_t method = 0;
        std::uint32_t compressedSize = 0;
        std::uint32_t uncompressedSize = 0;
        std::uint32_t localHeaderOffset = 0;

        [[nodiscard]] bool isDirectory() const { return !name.empty() && name.back() == '/'; }
    };

    explicit ZipArchive(const std::filesystem::path& path);
    explicit ZipArchive(std::vector<std::uint8_t> data);

    [[nodiscard]] const std::vector<Entry>& entries() const { return m_entries; }
    [[nodiscard]] const Entry* find(const std::string& name) const;
    [[nodiscard]] std::vector<std::uint8_t> read(const Entry& entry) const;

private:
    void readCentralDirectory();

    std::vector<std::uint8_t> m_data;
    std::vector<Entry> m_entries;
};

} // namespace fission::io
