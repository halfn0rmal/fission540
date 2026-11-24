add_library(fission_ui
    src/MainWindow.cpp
    src/BoxDialog.cpp
    include/fission/ui/MainWindow.h
    include/fission/ui/BoxDialog.h
)
add_library(Fission::ui ALIAS fission_ui)
target_include_directories(fission_ui PUBLIC include)
target_link_libraries(fission_ui PUBLIC Fission::core Fission::features Fission::viewer Qt6::Widgets)
fission_set_warnings(fission_ui)
