#pragma once

#include "fission/kernel/Shape.h"

#include <AIS_InteractiveContext.hxx>
#include <AIS_Shape.hxx>
#include <AIS_ViewController.hxx>
#include <V3d_View.hxx>
#include <V3d_Viewer.hxx>

#include <QWidget>

namespace fission::viewer {

// 3D viewport backed by an OCCT V3d view rendered into this widget's native X11 window.
//
// Navigation follows Fusion 360 defaults:
//   middle drag         pan
//   shift + middle drag orbit
//   wheel               zoom at cursor
//   left click          select / ViewCube
class OcctViewport : public QWidget, protected AIS_ViewController {
    Q_OBJECT

public:
    explicit OcctViewport(QWidget* parent = nullptr);
    ~OcctViewport() override;

    // Replaces the displayed body.
    void setBody(const kernel::Shape& body);
    void fitAll();

    QPaintEngine* paintEngine() const override { return nullptr; }

protected:
    void showEvent(QShowEvent* event) override;
    void paintEvent(QPaintEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;

    void handleViewRedraw(const Handle(AIS_InteractiveContext)& context,
                          const Handle(V3d_View)& view) override;

private:
    void initViewer();
    void configureMouseGestures();
    Graphic3d_Vec2i toPixels(const QPointF& pos) const;

    Handle(V3d_Viewer) m_viewer;
    Handle(V3d_View) m_view;
    Handle(AIS_InteractiveContext) m_context;
    Handle(AIS_Shape) m_bodyPresentation;
    kernel::Shape m_pendingBody;
};

} // namespace fission::viewer
