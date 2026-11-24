add_library(fission_core
    src/Feature.cpp
    src/Timeline.cpp
    src/Document.cpp
)
add_library(Fission::core ALIAS fission_core)
target_include_directories(fission_core PUBLIC include)
target_link_libraries(fission_core PUBLIC Fission::kernel)
fission_set_warnings(fission_core)
