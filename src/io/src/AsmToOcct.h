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
    std::vector<std::string> warnings;
};

// Converts every body in a parsed ASM document to OCCT, scaled to millimetres.
// Faces with unsupported geometry are skipped and reported in `stats`.
TopoDS_Shape convertToOcct(const sab::Document& doc, ConversionStats& stats);

} // namespace fission::io::detail
