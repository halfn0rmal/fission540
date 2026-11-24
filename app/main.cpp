#include "fission/ui/MainWindow.h"

#include <QApplication>

#include <cstdlib>

int main(int argc, char* argv[]) {
    // The OCCT viewer renders into a native X11 window, so run through XWayland
    // on Wayland sessions unless the user overrides it.
    if (std::getenv("QT_QPA_PLATFORM") == nullptr) {
        setenv("QT_QPA_PLATFORM", "xcb", 0);
    }

    QApplication app(argc, argv);
    QApplication::setApplicationName("Fission540");
    QApplication::setApplicationVersion("0.1.0");

    fission::ui::MainWindow window;
    window.show();
    return QApplication::exec();
}
