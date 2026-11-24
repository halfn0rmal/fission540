find_package(ZLIB REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(ZSTD REQUIRED IMPORTED_TARGET libzstd)

add_library(fission_io
    src/ZipArchive.cpp
    src/Sab.cpp
    src/AsmToOcct.cpp
    src/F3dImport.cpp
    src/F3dDesign.cpp
    src/StepExport.cpp
)
add_library(Fission::io ALIAS fission_io)
target_include_directories(fission_io PUBLIC include)
target_link_libraries(fission_io PUBLIC Fission::kernel PRIVATE ZLIB::ZLIB PkgConfig::ZSTD)
fission_link_occt(fission_io PRIVATE
    TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep TKGeomAlgo TKTopAlgo TKShHealing
    TKXSBase TKSTEP TKSTEPBase TKSTEPAttr TKSTEP209)
fission_set_warnings(fission_io)

add_executable(fission-f3d2step tools/f3d2step.cpp)
target_link_libraries(fission-f3d2step PRIVATE Fission::io)
fission_set_warnings(fission-f3d2step)
