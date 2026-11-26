#include "fission/ui/MainWindow.h"

#include <QApplication>

#include <cstdlib>
#include <string_view>

int main(int argc, char* argv[]) {
    // The OCCT viewer renders into a native X11 window, so run through XWayland
    // on Wayland sessions. Desktops often set QT_QPA_PLATFORM to a list such as
    // "wayland;xcb", where Qt takes the first entry, so any value naming
    // wayland is replaced; other values (offscreen, minimal) are kept.
    const char* platform = std::getenv("QT_QPA_PLATFORM");
    if (platform == nullptr || std::string_view(platform).find("wayland") != std::string_view::npos) {
        setenv("QT_QPA_PLATFORM", "xcb", 1);
    }

    QApplication app(argc, argv);
    QApplication::setApplicationName("Fission540");
    QApplication::setApplicationVersion("0.1.0");

    fission::ui::MainWindow window;
    window.show();
    return QApplication::exec();
}
