# Apply the project's warning set to a target.
function(fission_set_warnings target)
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor)
endfunction()

# OCCT headers are noisy; include them as system headers.
function(fission_link_occt target visibility)
    target_include_directories(${target} SYSTEM ${visibility} ${OpenCASCADE_INCLUDE_DIR})
    target_link_libraries(${target} ${visibility} ${ARGN})
endfunction()
