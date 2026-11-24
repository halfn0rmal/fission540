#pragma once

// Decoder for the parts of a Fusion design segment (MetaStream.dat + BulkStream.dat)
// needed to assemble geometry: components, which B-rep blob each uses, and occurrences
// with their placement. Format notes: docs/formats/f3d.md.

#include <array>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace fission::io::f3d {

// Class GUIDs from the MetaStream type table (stable across Fusion versions in samples).
inline constexpr const char* kComponentClass = "E03784ED-5E19-4E14-B9F2-3B07017018CD";
inline constexpr const char* kOccurrenceClass = "CE2913AA-CFE0-4F04-9102-24424ED3BCFA";
inline constexpr const char* kBodyContainerClass = "372234A0-2A6C-4122-8047-E74DBA04F326";

struct TypeEntry {
    std::string classGuid;  // upper case
    std::string parentGuid; // upper case
    std::string module;
    std::vector<std::uint64_t> objectIds;
};

struct ComponentDef {
    std::uint64_t id = 0;
    std::string name;
    std::string blobGuid; // B-rep blob BREP.<guid>.smb, empty if none
};

struct Occurrence {
    std::uint64_t id = 0;
    std::uint64_t component = 0;
    // Row-major 4x4; translation in m[3], m[7], m[11], in model units (cm).
    // Identity when Fusion stored no matrix.
    std::array<double, 16> matrix{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    bool identity = true;
};

struct Design {
    std::vector<TypeEntry> types;
    std::vector<ComponentDef> components;
    std::vector<Occurrence> occurrences;
    std::vector<std::string> warnings;

    [[nodiscard]] const ComponentDef* component(std::uint64_t id) const;
};

[[nodiscard]] std::vector<TypeEntry> parseTypeTable(std::span<const std::uint8_t> meta);

// Byte offset of the header of object `id` in BulkStream: u32 n, n ASCII digits, u64 id.
[[nodiscard]] std::optional<std::size_t> findObjectHeader(std::span<const std::uint8_t> bulk,
                                                          std::uint64_t id);

[[nodiscard]] std::optional<Occurrence> parseOccurrence(std::span<const std::uint8_t> bulk,
                                                        std::uint64_t id);

[[nodiscard]] Design parseDesign(std::span<const std::uint8_t> meta,
                                 std::span<const std::uint8_t> bulk);

} // namespace fission::io::f3d
