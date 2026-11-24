#pragma once

#include "fission/core/Document.h"

#include <QMainWindow>

class QListWidget;
class QListWidgetItem;
class QTreeWidget;

namespace fission::viewer {
class OcctViewport;
}

namespace fission::ui {

// Fusion-style layout: browser on the left, viewport in the centre,
// timeline along the bottom.
class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(QWidget* parent = nullptr);

private:
    void createActions();
    void createBrowser();
    void createTimeline();

    void addBox();
    void onTimelineActivated(QListWidgetItem* item);
    void recompute();
    void refreshPanels();

    core::Document m_document;
    viewer::OcctViewport* m_viewport = nullptr;
    QTreeWidget* m_browser = nullptr;
    QListWidget* m_timeline = nullptr;
};

} // namespace fission::ui
