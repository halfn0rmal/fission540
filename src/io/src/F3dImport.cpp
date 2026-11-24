#include "fission/io/F3dImport.h"

#include "AsmToOcct.h"
#include "fission/io/F3dDesign.h"
#include "fission/io/Sab.h"
#include "fission/io/ZipArchive.h"
#include "fission/kernel/occt/Native.h"

#include <BRep_Builder.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Trsf.hxx>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <optional>
#include <set>

namespace fission::io {
namespace {

// Fusion's internal length unit is the centimetre; design-stream placements use it.
constexpr double kMmPerDesignUnit = 10.0;

bool endsWith(const std::string& s, const std::string& suffix) {
    return s.size() >= suffix.size() &&
           s.compare(s.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool startsWith(const std::string& s, const std::string& prefix) {
    return s.rfind(prefix, 0) == 0;
}

std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

// "…/Breps.BlobParts/BREP.<guid>.smb" -> "<guid>" (lower case)
std::optional<std::string> blobGuid(const std::string& entryName) {
    const auto at = entryName.rfind("BREP.");
    if (at == std::string::npos || !endsWith(entryName, ".smb")) {
        return std::nullopt;
    }
    const std::size_t start = at + 5;
    return lower(entryName.substr(start, entryName.size() - 4 - start));
}

void accumulate(F3dImportResult& result, const detail::ConversionStats& stats) {
    result.bodies += stats.bodies;
    result.solids += stats.solids;
    result.faces += stats.faces;
    result.skippedFaces += stats.skippedFaces;
    result.ignoredBodies += stats.ignoredBodies;
    result.warnings.insert(result.warnings.end(), stats.warnings.begin(), stats.warnings.end());
}

// The main design segment's MetaStream/BulkStream pair, if present.
std::optional<f3d::Design> readDesign(const ZipArchive& zip, std::vector<std::string>& warnings) {
    for (const ZipArchive::Entry& e : zip.entries()) {
        if (!endsWith(e.name, "/MetaStream.dat") || startsWith(e.name, "Animation")) {
            continue;
        }
        const std::string dir = e.name.substr(0, e.name.size() - std::string("MetaStream.dat").size());
        const bool designSegment = dir.find("FusionDesignSegmentType") != std::string::npos ||
                                   endsWith(dir, "/Design1/");
        const ZipArchive::Entry* bulk = zip.find(dir + "BulkStream.dat");
        if (!designSegment || bulk == nullptr) {
            continue;
        }
        try {
            const auto meta = zip.read(e);
            const auto bulkData = zip.read(*bulk);
            return f3d::parseDesign(meta, bulkData);
        } catch (const std::exception& ex) {
            warnings.push_back(std::string("design data: ") + ex.what());
        }
    }
    return std::nullopt;
}

gp_Trsf toTrsf(const std::array<double, 16>& m) {
    gp_Trsf t;
    t.SetValues(m[0], m[1], m[2], m[3] * kMmPerDesignUnit, //
                m[4], m[5], m[6], m[7] * kMmPerDesignUnit, //
                m[8], m[9], m[10], m[11] * kMmPerDesignUnit);
    return t;
}

} // namespace

F3dImportResult importAsmBlob(std::span<const std::uint8_t> data) {
    F3dImportResult result;
    detail::ConversionStats stats;
    const sab::Document doc = sab::parse(data);
    result.shape = kernel::occt::wrap(detail::convertToOcct(doc, stats));
    result.blobs = 1;
    accumulate(result, stats);
    return result;
}

F3dImportResult importF3d(const std::filesystem::path& path) {
    const ZipArchive zip(path);
    F3dImportResult result;

    std::map<std::string, const ZipArchive::Entry*> blobEntries;
    for (const ZipArchive::Entry& entry : zip.entries()) {
        // .smb = current geometry; .smbh = history states (skipped).
        // The Animation workspace holds no design geometry of its own.
        if (startsWith(entry.name, "Animation")) {
            continue;
        }
        if (auto guid = blobGuid(entry.name)) {
            blobEntries[*guid] = &entry;
        }
    }
    if (blobEntries.empty()) {
        throw IoError("no B-rep geometry found in " + path.string());
    }

    // Each blob is converted once and shared by all occurrences of its component.
    std::map<std::string, std::optional<TopoDS_Shape>> converted;
    auto convertBlob = [&](const std::string& guid) -> std::optional<TopoDS_Shape> {
        if (auto it = converted.find(guid); it != converted.end()) {
            return it->second;
        }
        std::optional<TopoDS_Shape> shape;
        auto entry = blobEntries.find(guid);
        if (entry == blobEntries.end()) {
            result.warnings.push_back("blob " + guid + " referenced but missing");
        } else {
            try {
                const std::vector<std::uint8_t> data = zip.read(*entry->second);
                const sab::Document doc = sab::parse(data);
                detail::ConversionStats stats;
                shape = detail::convertToOcct(doc, stats);
                ++result.blobs;
                accumulate(result, stats);
            } catch (const IoError& e) {
                result.warnings.push_back(entry->second->name + ": " + e.what());
            }
        }
        converted.emplace(guid, shape);
        return shape;
    };

    BRep_Builder builder;
    TopoDS_Compound all;
    builder.MakeCompound(all);

    const std::optional<f3d::Design> design = readDesign(zip, result.warnings);
    const bool haveComponents =
        design && std::any_of(design->components.begin(), design->components.end(),
                              [](const f3d::ComponentDef& c) { return !c.blobGuid.empty(); });

    if (haveComponents) {
        std::vector<f3d::Occurrence> occurrences = design->occurrences;
        // Components with geometry but no decoded occurrence go at the origin. This is
        // normal for the root component, whose occurrence uses a different layout.
        std::set<std::uint64_t> placed;
        for (const f3d::Occurrence& occ : occurrences) {
            placed.insert(occ.component);
        }
        int unplaced = 0;
        for (const f3d::ComponentDef& c : design->components) {
            if (!c.blobGuid.empty() && !placed.count(c.id)) {
                f3d::Occurrence origin;
                origin.component = c.id;
                occurrences.push_back(origin);
                ++unplaced;
            }
        }
        if (unplaced > 1) {
            result.warnings.push_back(std::to_string(unplaced - 1) +
                                      " component(s) placed at the origin: occurrence not decoded");
            result.warnings.insert(result.warnings.end(), design->warnings.begin(),
                                   design->warnings.end());
        }

        std::set<std::string> used;
        bool warnedRotation = false;
        for (const f3d::Occurrence& occ : occurrences) {
            const f3d::ComponentDef* comp = design->component(occ.component);
            if (comp == nullptr || comp->blobGuid.empty()) {
                continue; // component without its own geometry
            }
            const std::string guid = lower(comp->blobGuid);
            const std::optional<TopoDS_Shape> shape = convertBlob(guid);
            if (!shape || shape->IsNull()) {
                continue;
            }
            used.insert(guid);
            const auto& m = occ.matrix;
            const bool rotated = std::abs(m[0] - 1) + std::abs(m[5] - 1) + std::abs(m[10] - 1) +
                                     std::abs(m[1]) + std::abs(m[2]) + std::abs(m[4]) +
                                     std::abs(m[6]) + std::abs(m[8]) + std::abs(m[9]) >
                                 1e-9;
            if (rotated && !warnedRotation) {
                warnedRotation = true;
                result.warnings.push_back("rotated occurrences: rotation convention not yet "
                                          "verified against a sample, check orientation");
            }
            F3dInstance instance;
            instance.component = comp->name;
            instance.transform = occ.matrix;
            for (int i : {3, 7, 11}) {
                instance.transform[i] *= kMmPerDesignUnit;
            }
            builder.Add(all, occ.identity ? *shape
                                          : shape->Moved(TopLoc_Location(toTrsf(occ.matrix))));
            result.instances.push_back(std::move(instance));
        }
        const std::size_t unused = blobEntries.size() - used.size();
        if (unused > 0) {
            result.warnings.push_back(std::to_string(unused) +
                                      " blob(s) not referenced by any occurrence were skipped");
        }
    } else {
        result.warnings.push_back("component placement could not be decoded; all geometry is "
                                  "shown at its stored position");
        for (const auto& blob : blobEntries) {
            if (auto shape = convertBlob(blob.first); shape && !shape->IsNull()) {
                builder.Add(all, *shape);
            }
        }
    }

    if (result.blobs == 0) {
        throw IoError("no readable B-rep geometry in " + path.string());
    }
    result.shape = kernel::occt::wrap(all);
    return result;
}

} // namespace fission::io
