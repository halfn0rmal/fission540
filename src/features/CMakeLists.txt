add_library(fission_features
    src/BoxFeature.cpp
    src/ImportedBodyFeature.cpp
)
add_library(Fission::features ALIAS fission_features)
target_include_directories(fission_features PUBLIC include)
target_link_libraries(fission_features PUBLIC Fission::core)
fission_set_warnings(fission_features)
