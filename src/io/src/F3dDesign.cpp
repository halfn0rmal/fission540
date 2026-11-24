#include "fission/io/F3dDesign.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstring>
#include <set>

namespace fission::io::f3d {
namespace {

using Bytes = std::span<const std::uint8_t>;

std::uint32_t u32(Bytes b, std::size_t at) {
    std::uint32_t v = 0;
    std::memcpy(&v, b.data() + at, 4);
    return v;
}

std::uint64_t u64(Bytes b, std::size_t at) {
    std::uint64_t v = 0;
    std::memcpy(&v, b.data() + at, 8);
    return v;
}

double f64(Bytes b, std::size_t at) {
    double v = 0;
    std::memcpy(&v, b.data() + at, 8);
    return v;
}

bool isGuid(Bytes b, std::size_t at) {
    if (at + 36 > b.size()) {
        return false;
    }
    for (std::size_t i = 0; i < 36; ++i) {
        const char c = static_cast<char>(b[at + i]);
        const bool dash = i == 8 || i == 13 || i == 18 || i == 23;
        if (dash ? c != '-' : !std::isxdigit(static_cast<unsigned char>(c))) {
            return false;
        }
    }
    return true;
}

std::string upper(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return s;
}

std::string ascii(Bytes b, std::size_t at, std::size_t n) {
    return {reinterpret_cast<const char*>(b.data() + at), n};
}

// Finds `needle` in [from, to).
std::optional<std::size_t> find(Bytes hay, const std::vector<std::uint8_t>& needle,
                                std::size_t from, std::size_t to) {
    to = std::min(to, hay.size());
    if (from >= to || needle.empty() || to - from < needle.size()) {
        return std::nullopt;
    }
    auto begin = hay.begin() + static_cast<std::ptrdiff_t>(from);
    auto end = hay.begin() + static_cast<std::ptrdiff_t>(to);
    auto it = std::search(begin, end, needle.begin(), needle.end());
    if (it == end) {
        return std::nullopt;
    }
    return static_cast<std::size_t>(it - hay.begin());
}

std::vector<std::uint8_t> le64(std::uint64_t v) {
    std::vector<std::uint8_t> out(8);
    std::memcpy(out.data(), &v, 8);
    return out;
}

std::vector<std::uint8_t> utf16(const std::string& s) {
    std::vector<std::uint8_t> out;
    for (char c : s) {
        out.push_back(static_cast<std::uint8_t>(c));
        out.push_back(0);
    }
    return out;
}

// Length-prefixed (u32 chars) UTF-16 strings of printable ASCII within [from, to).
std::vector<std::string> utf16Strings(Bytes b, std::size_t from, std::size_t to) {
    std::vector<std::string> out;
    to = std::min(to, b.size());
    for (std::size_t p = from; p + 4 < to;) {
        const std::uint32_t n = u32(b, p);
        if (n >= 2 && n <= 128 && p + 4 + 2 * n <= to) {
            std::string s;
            bool ok = true;
            for (std::uint32_t i = 0; i < n && ok; ++i) {
                const std::uint8_t lo = b[p + 4 + 2 * i];
                const std::uint8_t hi = b[p + 5 + 2 * i];
                ok = hi == 0 && lo >= 0x20 && lo < 0x7f;
                s.push_back(static_cast<char>(lo));
            }
            if (ok) {
                out.push_back(std::move(s));
                p += 4 + 2 * n;
                continue;
            }
        }
        ++p;
    }
    return out;
}

bool looksInternal(const std::string& s) {
    const bool guid = s.size() >= 36 && s.size() <= 37 &&
                      isGuid(Bytes(reinterpret_cast<const std::uint8_t*>(s.data()), s.size()), 0);
    static const char* const prefixes[] = {"PrismMaterial", "Prism-", "BREP.", "ProteinAsset",
                                           "1_", "arrangementsContainer", "DesignConfiguration"};
    return guid || std::any_of(std::begin(prefixes), std::end(prefixes),
                               [&](const char* p) { return s.rfind(p, 0) == 0; });
}

// Reference token: 0x01 followed by the u64 object id.
std::optional<std::uint64_t> refAt(Bytes b, std::size_t at) {
    if (at + 9 > b.size() || b[at] != 1) {
        return std::nullopt;
    }
    return u64(b, at + 1);
}

bool validPlacement(const std::array<double, 16>& m) {
    if (std::abs(m[12]) > 1e-9 || std::abs(m[13]) > 1e-9 || std::abs(m[14]) > 1e-9 ||
        std::abs(m[15] - 1.0) > 1e-9) {
        return false;
    }
    for (int r = 0; r < 3; ++r) {
        for (int s = r; s < 3; ++s) {
            double dot = 0;
            for (int k = 0; k < 3; ++k) {
                dot += m[4 * r + k] * m[4 * s + k];
            }
            if (std::abs(dot - (r == s ? 1.0 : 0.0)) > 1e-6) {
                return false;
            }
        }
    }
    return true;
}

} // namespace

const ComponentDef* Design::component(std::uint64_t id) const {
    auto it = std::find_if(components.begin(), components.end(),
                           [&](const ComponentDef& c) { return c.id == id; });
    return it == components.end() ? nullptr : &*it;
}

std::vector<TypeEntry> parseTypeTable(Bytes meta) {
    // Entry: u32 36, class GUID, u32 36, parent GUID, u32 index, u32 n, module name,
    //        u32 count, count x u64 object ids.
    std::vector<TypeEntry> types;
    std::size_t p = 0;
    while (p + 84 <= meta.size()) {
        if (u32(meta, p) == 36 && isGuid(meta, p + 4) && u32(meta, p + 40) == 36 &&
            isGuid(meta, p + 44) && p + 88 <= meta.size()) {
            const std::uint32_t nameLen = u32(meta, p + 84);
            const std::size_t nameAt = p + 88;
            if (nameLen >= 1 && nameLen <= 64 && nameAt + nameLen + 4 <= meta.size()) {
                const std::string module = ascii(meta, nameAt, nameLen);
                const bool ident = std::all_of(module.begin(), module.end(), [](char c) {
                    return std::isalnum(static_cast<unsigned char>(c)) || c == '_';
                });
                const std::size_t countAt = nameAt + nameLen;
                const std::uint32_t count = u32(meta, countAt);
                if (ident && count <= 1'000'000 && countAt + 4 + 8ull * count <= meta.size()) {
                    TypeEntry t;
                    t.classGuid = upper(ascii(meta, p + 4, 36));
                    t.parentGuid = upper(ascii(meta, p + 44, 36));
                    t.module = module;
                    for (std::uint32_t i = 0; i < count; ++i) {
                        t.objectIds.push_back(u64(meta, countAt + 4 + 8 * i));
                    }
                    types.push_back(std::move(t));
                    p = countAt + 4 + 8ull * count;
                    continue;
                }
            }
        }
        ++p;
    }
    return types;
}

std::optional<std::size_t> findObjectHeader(Bytes bulk, std::uint64_t id) {
    const std::vector<std::uint8_t> needle = le64(id);
    std::size_t from = 0;
    while (auto hit = find(bulk, needle, from, bulk.size())) {
        const std::size_t p = *hit;
        for (std::size_t n = 1; n <= 8; ++n) {
            if (p < 4 + n || u32(bulk, p - 4 - n) != n) {
                continue;
            }
            bool digits = true;
            for (std::size_t i = p - n; i < p && digits; ++i) {
                digits = std::isdigit(bulk[i]) != 0;
            }
            if (digits) {
                return p - 4 - n;
            }
        }
        from = p + 1;
    }
    return std::nullopt;
}

std::optional<Occurrence> parseOccurrence(Bytes bulk, std::uint64_t id) {
    const auto header = findObjectHeader(bulk, id);
    if (!header) {
        return std::nullopt;
    }
    // Change-flag names end with "Transform", followed by the self and component references.
    std::vector<std::uint8_t> mark = {9, 0, 0, 0};
    for (char c : std::string("Transform")) {
        mark.push_back(static_cast<std::uint8_t>(c));
    }
    mark.push_back(0);
    const auto m = find(bulk, mark, *header, *header + 512);
    if (!m) {
        return std::nullopt;
    }
    std::size_t p = *m + mark.size();
    if (!refAt(bulk, p)) {
        return std::nullopt;
    }
    p += 9;
    for (int i = 0; i < 8 && p < bulk.size() && bulk[p] == 0; ++i) {
        ++p; // trailing bytes after a reference vary in length
    }
    const auto component = refAt(bulk, p);
    if (!component) {
        return std::nullopt;
    }
    p += 9;

    // The component reference repeats; the placement follows the second one:
    // u8 1 = identity (no matrix), u8 0 = 16 doubles (row-major).
    std::vector<std::uint8_t> ref = {1};
    const auto idBytes = le64(*component);
    ref.insert(ref.end(), idBytes.begin(), idBytes.end());
    const auto second = find(bulk, ref, p, p + 768);
    if (!second) {
        return std::nullopt;
    }
    const std::size_t flagAt = *second + 11;
    if (flagAt >= bulk.size()) {
        return std::nullopt;
    }

    Occurrence occ;
    occ.id = id;
    occ.component = *component;
    if (bulk[flagAt] == 1) {
        return occ;
    }
    if (bulk[flagAt] != 0 || flagAt + 1 + 128 > bulk.size()) {
        return std::nullopt;
    }
    for (std::size_t i = 0; i < 16; ++i) {
        occ.matrix[i] = f64(bulk, flagAt + 1 + 8 * i);
    }
    if (!validPlacement(occ.matrix)) {
        return std::nullopt;
    }
    occ.identity = false;
    return occ;
}

Design parseDesign(Bytes meta, Bytes bulk) {
    Design design;
    design.types = parseTypeTable(meta);

    auto idsOf = [&](const char* classGuid) {
        std::vector<std::uint64_t> ids;
        for (const TypeEntry& t : design.types) {
            if (t.classGuid == classGuid) {
                ids.insert(ids.end(), t.objectIds.begin(), t.objectIds.end());
            }
        }
        return ids;
    };

    // Components and their names.
    std::set<std::uint64_t> componentIds;
    for (std::uint64_t id : idsOf(kComponentClass)) {
        ComponentDef c;
        c.id = id;
        if (const auto h = findObjectHeader(bulk, id)) {
            for (const std::string& s : utf16Strings(bulk, *h, *h + 0x800)) {
                if (!looksInternal(s)) {
                    c.name = s;
                    break;
                }
            }
        }
        componentIds.insert(id);
        design.components.push_back(std::move(c));
    }

    // Body containers link a component to its B-rep blob.
    const std::vector<std::uint8_t> brep = utf16("BREP.");
    for (std::uint64_t id : idsOf(kBodyContainerClass)) {
        const auto h = findObjectHeader(bulk, id);
        if (!h) {
            continue;
        }
        const std::size_t end = std::min(bulk.size(), *h + 0x800);
        std::optional<std::uint64_t> owner;
        for (std::size_t p = *h + 1; p + 9 <= end && !owner; ++p) {
            if (auto r = refAt(bulk, p); r && componentIds.count(*r)) {
                owner = r;
            }
        }
        std::string blob;
        for (auto at = find(bulk, brep, *h, end); at && blob.empty();
             at = find(bulk, brep, *at + 1, end)) {
            const std::size_t g = *at + brep.size();
            if (g + 2 * 36 + 10 > bulk.size()) {
                break;
            }
            std::string guid;
            for (std::size_t i = 0; i < 36; ++i) {
                guid.push_back(static_cast<char>(bulk[g + 2 * i]));
            }
            const std::string ext = ascii(bulk, g + 72, 10); // ".smb" + next char, UTF-16
            const bool smb = ext[0] == '.' && ext[2] == 's' && ext[4] == 'm' && ext[6] == 'b' &&
                             ext[8] != 'h';
            if (smb && isGuid(Bytes(reinterpret_cast<const std::uint8_t*>(guid.data()), 36), 0)) {
                blob = guid;
            }
        }
        if (owner && !blob.empty()) {
            for (ComponentDef& c : design.components) {
                if (c.id == *owner) {
                    c.blobGuid = blob;
                }
            }
        }
    }

    for (std::uint64_t id : idsOf(kOccurrenceClass)) {
        if (auto occ = parseOccurrence(bulk, id)) {
            if (componentIds.count(occ->component)) {
                design.occurrences.push_back(*occ);
                continue;
            }
        }
        design.warnings.push_back("could not decode occurrence " + std::to_string(id));
    }
    return design;
}

} // namespace fission::io::f3d
