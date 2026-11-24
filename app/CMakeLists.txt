add_executable(fission540 main.cpp)
target_link_libraries(fission540 PRIVATE Fission::ui)
fission_set_warnings(fission540)
