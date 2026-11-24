add_library(fission_kernel
    src/Shape.cpp
    src/Primitives.cpp
    src/Booleans.cpp
    src/Properties.cpp
)
add_library(Fission::kernel ALIAS fission_kernel)
target_include_directories(fission_kernel PUBLIC include)
fission_set_warnings(fission_kernel)
# OCCT is PRIVATE: only the occt/ escape-hatch header exposes it, and consumers
# that include it (viewer) link OCCT themselves.
fission_link_occt(fission_kernel PRIVATE
    TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep TKGeomAlgo TKTopAlgo TKPrim TKBO)
