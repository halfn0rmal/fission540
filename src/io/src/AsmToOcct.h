#pragma once

#include "fission/io/Sab.h"

#include <TopoDS_Shape.hxx>

#include <string>
#include <vector>

namespace fission::io::detail {

struct ConversionStats {
    int bodies = 0;
    int solids = 0;
    int faces = 0;
    int skippedFaces = 0;
    int skippedEdges = 0;
    int ignoredBodies = 0; // feature-cache / sketch bodies not selected as current
    int sewedShells = 0;   // shells closed by sewing after conversion
    std::vector<std::string> warnings;
};

enum class BodySelection {
    // Only the component's current bodies (heuristic, see docs/formats/f3d.md):
    // the leading run of top-level body records; if the blob uses timestamp
    // attributes, only tagged ones; otherwise only closed solids.
    Current,
    // Every body record in the blob (debugging).
    All,
};

// Converts bodies in a parsed ASM document to OCCT, scaled to millimetres.
// Faces with unsupported geometry are skipped and reported in `stats`.
TopoDS_Shape convertToOcct(const sab::Document& doc, ConversionStats& stats,
                           BodySelection selection = BodySelection::Current);

} // namespace fission::io::detail
