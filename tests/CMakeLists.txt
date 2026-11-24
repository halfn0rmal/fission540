find_package(Catch2 3 QUIET)
if(NOT Catch2_FOUND)
    include(FetchContent)
    FetchContent_Declare(Catch2
        GIT_REPOSITORY https://github.com/catchorg/Catch2.git
        GIT_TAG v3.5.4)
    FetchContent_MakeAvailable(Catch2)
endif()

add_executable(fission_tests
    kernel/test_primitives.cpp
    core/test_timeline.cpp
    io/test_sab.cpp
    io/test_f3d_design.cpp
    io/test_f3d_samples.cpp
)
target_link_libraries(fission_tests PRIVATE Fission::features Fission::io Catch2::Catch2WithMain)
fission_set_warnings(fission_tests)

include(Catch)
catch_discover_tests(fission_tests)
