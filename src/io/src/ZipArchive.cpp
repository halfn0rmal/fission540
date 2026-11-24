#include "fission/io/ZipArchive.h"

#include <zlib.h>
#include <zstd.h>

#include <algorithm>
#include <cstring>
#include <fstream>
#include <iterator>

namespace fission::io {
namespace {

constexpr std::uint32_t kEndOfCentralDirSig = 0x06054b50;
constexpr std::uint32_t kCentralDirSig = 0x02014b50;
constexpr std::uint32_t kLocalHeaderSig = 0x04034b50;

constexpr std::uint16_t kMethodStored = 0;
constexpr std::uint16_t kMethodDeflate = 8;
constexpr std::uint16_t kMethodZstd = 93;

std::uint16_t u16(const std::vector<std::uint8_t>& d, std::size_t at) {
    if (at + 2 > d.size()) {
        throw IoError("zip: truncated");
    }
    return static_cast<std::uint16_t>(d[at] | (d[at + 1] << 8));
}

std::uint32_t u32(const std::vector<std::uint8_t>& d, std::size_t at) {
    if (at + 4 > d.size()) {
        throw IoError("zip: truncated");
    }
    return static_cast<std::uint32_t>(d[at]) | (static_cast<std::uint32_t>(d[at + 1]) << 8) |
           (static_cast<std::uint32_t>(d[at + 2]) << 16) |
           (static_cast<std::uint32_t>(d[at + 3]) << 24);
}

std::vector<std::uint8_t> inflateRaw(const std::uint8_t* src, std::size_t size, std::size_t outSize) {
    std::vector<std::uint8_t> out(outSize);
    z_stream zs{};
    if (inflateInit2(&zs, -MAX_WBITS) != Z_OK) {
        throw IoError("zip: inflateInit failed");
    }
    zs.next_in = const_cast<Bytef*>(src);
    zs.avail_in = static_cast<uInt>(size);
    zs.next_out = out.data();
    zs.avail_out = static_cast<uInt>(out.size());
    const int rc = inflate(&zs, Z_FINISH);
    inflateEnd(&zs);
    if (rc != Z_STREAM_END || zs.total_out != outSize) {
        throw IoError("zip: deflate data corrupt");
    }
    return out;
}

std::vector<std::uint8_t> decompressZstd(const std::uint8_t* src, std::size_t size,
                                         std::size_t outSize) {
    std::vector<std::uint8_t> out(outSize);
    const std::size_t rc = ZSTD_decompress(out.data(), out.size(), src, size);
    if (ZSTD_isError(rc) || rc != outSize) {
        throw IoError(std::string("zip: zstd data corrupt: ") +
                      (ZSTD_isError(rc) ? ZSTD_getErrorName(rc) : "size mismatch"));
    }
    return out;
}

} // namespace

ZipArchive::ZipArchive(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw IoError("cannot open " + path.string());
    }
    m_data.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    readCentralDirectory();
}

ZipArchive::ZipArchive(std::vector<std::uint8_t> data) : m_data(std::move(data)) {
    readCentralDirectory();
}

void ZipArchive::readCentralDirectory() {
    // End-of-central-directory record is in the last 22 + 65535 bytes.
    if (m_data.size() < 22) {
        throw IoError("zip: file too small");
    }
    const std::size_t searchStart = m_data.size() > 22 + 0xFFFF ? m_data.size() - 22 - 0xFFFF : 0;
    std::size_t eocd = std::string::npos;
    for (std::size_t i = m_data.size() - 22 + 1; i-- > searchStart;) {
        if (u32(m_data, i) == kEndOfCentralDirSig) {
            eocd = i;
            break;
        }
    }
    if (eocd == std::string::npos) {
        throw IoError("zip: end of central directory not found");
    }

    const std::uint16_t count = u16(m_data, eocd + 10);
    const std::uint32_t dirOffset = u32(m_data, eocd + 16);
    if (dirOffset == 0xFFFFFFFF) {
        throw IoError("zip: zip64 archives are not supported");
    }

    std::size_t at = dirOffset;
    m_entries.reserve(count);
    for (std::uint16_t i = 0; i < count; ++i) {
        if (u32(m_data, at) != kCentralDirSig) {
            throw IoError("zip: bad central directory entry");
        }
        Entry e;
        e.method = u16(m_data, at + 10);
        e.compressedSize = u32(m_data, at + 20);
        e.uncompressedSize = u32(m_data, at + 24);
        const std::uint16_t nameLen = u16(m_data, at + 28);
        const std::uint16_t extraLen = u16(m_data, at + 30);
        const std::uint16_t commentLen = u16(m_data, at + 32);
        e.localHeaderOffset = u32(m_data, at + 42);
        if (at + 46 + nameLen > m_data.size()) {
            throw IoError("zip: truncated entry name");
        }
        e.name.assign(reinterpret_cast<const char*>(&m_data[at + 46]), nameLen);
        m_entries.push_back(std::move(e));
        at += 46 + nameLen + extraLen + commentLen;
    }
}

const ZipArchive::Entry* ZipArchive::find(const std::string& name) const {
    auto it = std::find_if(m_entries.begin(), m_entries.end(),
                           [&](const Entry& e) { return e.name == name; });
    return it == m_entries.end() ? nullptr : &*it;
}

std::vector<std::uint8_t> ZipArchive::read(const Entry& entry) const {
    const std::size_t at = entry.localHeaderOffset;
    if (u32(m_data, at) != kLocalHeaderSig) {
        throw IoError("zip: bad local header for " + entry.name);
    }
    const std::size_t dataStart = at + 30 + u16(m_data, at + 26) + u16(m_data, at + 28);
    if (dataStart + entry.compressedSize > m_data.size()) {
        throw IoError("zip: truncated data for " + entry.name);
    }
    const std::uint8_t* src = m_data.data() + dataStart;

    switch (entry.method) {
    case kMethodStored:
        return {src, src + entry.compressedSize};
    case kMethodDeflate:
        return inflateRaw(src, entry.compressedSize, entry.uncompressedSize);
    case kMethodZstd:
        return decompressZstd(src, entry.compressedSize, entry.uncompressedSize);
    default:
        throw IoError("zip: unsupported compression method " + std::to_string(entry.method) +
                      " for " + entry.name);
    }
}

} // namespace fission::io
