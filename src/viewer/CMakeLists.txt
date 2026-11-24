add_library(fission_viewer
    src/OcctViewport.cpp
    include/fission/viewer/OcctViewport.h
)
add_library(Fission::viewer ALIAS fission_viewer)
target_include_directories(fission_viewer PUBLIC include)
target_link_libraries(fission_viewer PUBLIC Fission::kernel Qt6::Widgets)
fission_link_occt(fission_viewer PUBLIC
    TKernel TKMath TKG3d TKBRep TKService TKV3d TKOpenGl)
fission_set_warnings(fission_viewer)
