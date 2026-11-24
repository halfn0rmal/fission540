#include "fission/io/F3dImport.h"

#include "AsmToOcct.h"
#include "fission/io/Sab.h"
#include "fission/io/ZipArchive.h"
#include "fission/kernel/occt/Native.h"

#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>

namespace fission::io {
namespace {

bool endsWith(const std::string& s, const std::string& suffix) {
    return s.size() >= suffix.size() && s.compare(s.size() - suffix.size(), suffix.size(), suffix) == 0;
}

void accumulate(F3dImportResult& result, const detail::ConversionStats& stats) {
    result.bodies += stats.bodies;
    result.solids += stats.solids;
    result.faces += stats.faces;
    result.skippedFaces += stats.skippedFaces;
    result.warnings.insert(result.warnings.end(), stats.warnings.begin(), stats.warnings.end());
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

    BRep_Builder builder;
    TopoDS_Compound all;
    builder.MakeCompound(all);

    for (const ZipArchive::Entry& entry : zip.entries()) {
        // .smb = current geometry; .smbh = history states (skipped).
        // The Animation workspace holds no design geometry of its own.
        if (!endsWith(entry.name, ".smb") || entry.name.rfind("Animation", 0) == 0) {
            continue;
        }
        const std::vector<std::uint8_t> data = zip.read(entry);
        if (!sab::hasMagic(data)) {
            result.warnings.push_back("skipped non-ASM blob " + entry.name);
            continue;
        }
        try {
            const sab::Document doc = sab::parse(data);
            detail::ConversionStats stats;
            TopoDS_Shape shape = detail::convertToOcct(doc, stats);
            builder.Add(all, shape);
            ++result.blobs;
            accumulate(result, stats);
        } catch (const IoError& e) {
            result.warnings.push_back(entry.name + ": " + e.what());
        }
    }

    if (result.blobs == 0) {
        throw IoError("no B-rep geometry found in " + path.string());
    }
    if (result.blobs > 1) {
        result.warnings.push_back("multiple components: placement is not decoded yet, bodies are "
                                  "shown at their stored positions");
    }
    result.shape = kernel::occt::wrap(all);
    return result;
}

} // namespace fission::io
