#include "fission/ui/MainWindow.h"

#include "fission/features/BoxFeature.h"
#include "fission/features/ImportedBodyFeature.h"
#include "fission/io/F3dImport.h"
#include "fission/kernel/Properties.h"
#include "fission/ui/BoxDialog.h"
#include "fission/viewer/OcctViewport.h"

#include <QAction>
#include <QComboBox>
#include <QDockWidget>
#include <QFileDialog>
#include <QFileInfo>
#include <QListWidget>
#include <QMenuBar>
#include <QMessageBox>
#include <QStringList>
#include <QStatusBar>
#include <QToolBar>
#include <QTreeWidget>

#include <exception>
#include <memory>

namespace fission::ui {

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
    setWindowTitle(tr("Fission540"));
    resize(1400, 900);

    m_viewport = new viewer::OcctViewport(this);
    setCentralWidget(m_viewport);

    createActions();
    createBrowser();
    createTimeline();
    refreshPanels();
    statusBar()->showMessage(tr("Ready"));
}

void MainWindow::createActions() {
    auto* fileMenu = menuBar()->addMenu(tr("&File"));
    QAction* importAction = fileMenu->addAction(tr("&Import..."));
    importAction->setShortcut(QKeySequence(Qt::CTRL | Qt::Key_I));
    connect(importAction, &QAction::triggered, this, &MainWindow::importFile);
    fileMenu->addSeparator();
    QAction* quit = fileMenu->addAction(tr("&Quit"));
    quit->setShortcut(QKeySequence::Quit);
    connect(quit, &QAction::triggered, this, &QWidget::close);

    auto* toolbar = addToolBar(tr("Design"));
    toolbar->setMovable(false);

    auto* workspace = new QComboBox(toolbar);
    workspace->addItem(tr("DESIGN"));
    toolbar->addWidget(workspace);
    toolbar->addSeparator();

    auto* createMenu = menuBar()->addMenu(tr("&Create"));
    QAction* box = createMenu->addAction(tr("Box"));
    connect(box, &QAction::triggered, this, &MainWindow::addBox);
    toolbar->addAction(box);

    auto* viewMenu = menuBar()->addMenu(tr("&View"));
    QAction* fit = viewMenu->addAction(tr("Fit"));
    fit->setShortcut(QKeySequence(Qt::Key_F6));
    connect(fit, &QAction::triggered, m_viewport, &viewer::OcctViewport::fitAll);
}

void MainWindow::createBrowser() {
    m_browser = new QTreeWidget(this);
    m_browser->setHeaderHidden(true);

    auto* dock = new QDockWidget(tr("Browser"), this);
    dock->setObjectName("browser");
    dock->setWidget(m_browser);
    addDockWidget(Qt::LeftDockWidgetArea, dock);
}

void MainWindow::createTimeline() {
    m_timeline = new QListWidget(this);
    m_timeline->setFlow(QListView::LeftToRight);
    m_timeline->setWrapping(false);
    m_timeline->setFixedHeight(56);
    m_timeline->setToolTip(tr("Double-click a feature to roll the timeline to it"));
    connect(m_timeline, &QListWidget::itemDoubleClicked, this, &MainWindow::onTimelineActivated);

    auto* dock = new QDockWidget(tr("Timeline"), this);
    dock->setObjectName("timeline");
    dock->setWidget(m_timeline);
    dock->setFeatures(QDockWidget::NoDockWidgetFeatures);
    addDockWidget(Qt::BottomDockWidgetArea, dock);
}

void MainWindow::addBox() {
    BoxDialog dialog(this);
    if (dialog.exec() != QDialog::Accepted) {
        return;
    }
    const std::string id = m_document.nextFeatureId();
    const std::string name = "Box" + std::to_string(m_document.timeline().size() + 1);
    m_document.timeline().insert(
        std::make_unique<features::BoxFeature>(id, name, dialog.params()));
    recompute();
}

void MainWindow::importFile() {
    const QString path = QFileDialog::getOpenFileName(this, tr("Import"), QString(),
                                                      tr("Fusion 360 design (*.f3d)"));
    if (path.isEmpty()) {
        return;
    }
    io::F3dImportResult result;
    try {
        result = io::importF3d(path.toStdString());
    } catch (const std::exception& e) {
        QMessageBox::critical(this, tr("Import failed"), QString::fromUtf8(e.what()));
        return;
    }

    const std::string name = QFileInfo(path).completeBaseName().toStdString();
    m_document.timeline().insert(std::make_unique<features::ImportedBodyFeature>(
        m_document.nextFeatureId(), name, result.shape, path.toStdString()));
    recompute();

    QString summary = tr("Imported %1 bodies, %2 faces.").arg(result.bodies).arg(result.faces);
    if (result.skippedFaces > 0) {
        summary += tr(" %1 faces could not be read.").arg(result.skippedFaces);
    }
    if (!result.warnings.empty()) {
        QStringList lines;
        for (const auto& w : result.warnings) {
            lines << QString::fromStdString(w);
        }
        QMessageBox::warning(this, tr("Import"), summary + "\n\n" + lines.join('\n'));
    } else {
        statusBar()->showMessage(summary);
    }
}

void MainWindow::onTimelineActivated(QListWidgetItem* item) {
    const int row = m_timeline->row(item);
    const auto index = static_cast<std::size_t>(row);
    auto& timeline = m_document.timeline();
    // Toggle: rolling to the feature that is already last re-runs the full timeline.
    timeline.setMarker(timeline.marker() == index + 1 ? timeline.size() : index + 1);
    recompute();
}

void MainWindow::recompute() {
    m_document.recompute();
    m_viewport->setBody(m_document.body());
    refreshPanels();
    statusBar()->showMessage(
        tr("Volume: %1 mm³").arg(kernel::volume(m_document.body()), 0, 'f', 3));
}

void MainWindow::refreshPanels() {
    const auto& timeline = m_document.timeline();

    m_timeline->clear();
    for (std::size_t i = 0; i < timeline.size(); ++i) {
        const core::Feature& feature = timeline.at(i);
        auto* item = new QListWidgetItem(QString::fromStdString(feature.name()), m_timeline);
        QString tip = QString::fromStdString(feature.typeName());
        if (feature.state() == core::FeatureState::Error) {
            item->setForeground(Qt::red);
            tip += "\n" + QString::fromStdString(feature.errorMessage());
        }
        if (i >= timeline.marker()) {
            item->setForeground(Qt::gray);
        }
        item->setToolTip(tip);
    }

    m_browser->clear();
    auto* root = new QTreeWidgetItem(m_browser, {tr("(Unsaved)")});
    auto* bodies = new QTreeWidgetItem(root, {tr("Bodies")});
    if (!m_document.body().isNull()) {
        new QTreeWidgetItem(bodies, {tr("Body1")});
    }
    new QTreeWidgetItem(root, {tr("Origin")});
    m_browser->expandAll();
}

} // namespace fission::ui
