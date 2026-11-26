#include "fission/viewer/OcctViewport.h"

#include "fission/kernel/occt/Native.h"

#include <AIS_ViewCube.hxx>
#include <Aspect_DisplayConnection.hxx>
#include <Font_FontMgr.hxx>
#include <Graphic3d_TransformPers.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <Prs3d_Drawer.hxx>
#include <Quantity_Color.hxx>
#include <Xw_Window.hxx>

#include <QFont>
#include <QFontInfo>
#include <QMouseEvent>
#include <QWheelEvent>

#include <utility>

namespace fission::viewer {
namespace {

// OCCT resolves the generic families through its own alias lists (DejaVu and
// the like), which match nothing on systems without those fonts, leaving the
// ViewCube unlabelled. Add whatever fontconfig picks for each family, via Qt.
void registerSystemFontAliases() {
    static const bool done = [] {
        const Handle(Font_FontMgr) fonts = Font_FontMgr::GetInstance();
        for (const auto& [alias, hint] : {std::pair{"sans-serif", QFont::SansSerif},
                                          std::pair{"serif", QFont::Serif},
                                          std::pair{"monospace", QFont::Monospace}}) {
            QFont font(QString::fromLatin1(alias));
            font.setStyleHint(hint);
            const QByteArray family = QFontInfo(font).family().toUtf8();
            if (!family.isEmpty()) {
                fonts->AddFontAlias(alias, TCollection_AsciiString(family.constData()));
            }
        }
        return true;
    }();
    (void)done;
}

Aspect_VKeyMouse toOcctButtons(Qt::MouseButtons buttons) {
    Aspect_VKeyMouse result = Aspect_VKeyMouse_NONE;
    if (buttons & Qt::LeftButton) {
        result |= Aspect_VKeyMouse_LeftButton;
    }
    if (buttons & Qt::MiddleButton) {
        result |= Aspect_VKeyMouse_MiddleButton;
    }
    if (buttons & Qt::RightButton) {
        result |= Aspect_VKeyMouse_RightButton;
    }
    return result;
}

Aspect_VKeyFlags toOcctModifiers(Qt::KeyboardModifiers modifiers) {
    Aspect_VKeyFlags result = Aspect_VKeyFlags_NONE;
    if (modifiers & Qt::ShiftModifier) {
        result |= Aspect_VKeyFlags_SHIFT;
    }
    if (modifiers & Qt::ControlModifier) {
        result |= Aspect_VKeyFlags_CTRL;
    }
    if (modifiers & Qt::AltModifier) {
        result |= Aspect_VKeyFlags_ALT;
    }
    return result;
}

} // namespace

OcctViewport::OcctViewport(QWidget* parent) : QWidget(parent) {
    // OCCT draws directly into the native window; Qt must not paint over it.
    setAttribute(Qt::WA_NativeWindow);
    setAttribute(Qt::WA_PaintOnScreen);
    setAttribute(Qt::WA_NoSystemBackground);
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
    setMinimumSize(200, 200);
    configureMouseGestures();
}

OcctViewport::~OcctViewport() = default;

void OcctViewport::configureMouseGestures() {
    myMouseGestureMap.Clear();
    myMouseGestureMap.Bind(Aspect_VKeyMouse_MiddleButton, AIS_MouseGesture_Pan);
    // Cast first: OR-ing two different enum types is deprecated in C++20.
    const unsigned int shiftMiddle = static_cast<unsigned int>(Aspect_VKeyMouse_MiddleButton) |
                                     static_cast<unsigned int>(Aspect_VKeyFlags_SHIFT);
    myMouseGestureMap.Bind(shiftMiddle, AIS_MouseGesture_RotateOrbit);
    SetAllowRotation(true);
}

void OcctViewport::initViewer() {
    if (!m_view.IsNull()) {
        return;
    }

    registerSystemFontAliases();
    Handle(Aspect_DisplayConnection) display = new Aspect_DisplayConnection();
    Handle(OpenGl_GraphicDriver) driver = new OpenGl_GraphicDriver(display, false);

    m_viewer = new V3d_Viewer(driver);
    m_viewer->SetDefaultLights();
    m_viewer->SetLightOn();

    m_context = new AIS_InteractiveContext(m_viewer);
    m_context->SetDisplayMode(AIS_Shaded, false);
    m_context->DefaultDrawer()->SetFaceBoundaryDraw(true);

    m_view = m_viewer->CreateView();
    Handle(Xw_Window) window = new Xw_Window(display, static_cast<Aspect_Drawable>(winId()));
    m_view->SetWindow(window);
    if (!window->IsMapped()) {
        window->Map();
    }

    m_view->SetBgGradientColors(Quantity_Color(0.86, 0.88, 0.92, Quantity_TOC_RGB),
                                Quantity_Color(0.62, 0.66, 0.72, Quantity_TOC_RGB),
                                Aspect_GradientFillMethod_Vertical, false);
    m_view->SetProj(V3d_XposYnegZpos);
    m_view->Camera()->SetProjectionType(Graphic3d_Camera::Projection_Perspective);

    Handle(AIS_ViewCube) cube = new AIS_ViewCube();
    cube->SetSize(55.0);
    cube->SetFontHeight(12.0);
    cube->SetTransformPersistence(new Graphic3d_TransformPers(
        Graphic3d_TMF_TriedronPers, Aspect_TOTP_RIGHT_UPPER, Graphic3d_Vec2i(85, 85)));
    m_context->Display(cube, false);

    m_view->MustBeResized();

    if (!m_pendingBody.isNull()) {
        setBody(m_pendingBody);
        m_pendingBody = {};
    }
}

void OcctViewport::setBody(const kernel::Shape& body) {
    if (m_context.IsNull()) {
        m_pendingBody = body;
        return;
    }
    if (!m_bodyPresentation.IsNull()) {
        m_context->Remove(m_bodyPresentation, false);
        m_bodyPresentation.Nullify();
    }
    if (!body.isNull()) {
        m_bodyPresentation = new AIS_Shape(kernel::occt::native(body));
        m_bodyPresentation->SetColor(Quantity_Color(0.72, 0.74, 0.77, Quantity_TOC_RGB));
        m_context->Display(m_bodyPresentation, AIS_Shaded, 0, false);
    }
    fitAll();
}

void OcctViewport::fitAll() {
    if (m_view.IsNull()) {
        return;
    }
    m_view->FitAll(0.2, false);
    update();
}

Graphic3d_Vec2i OcctViewport::toPixels(const QPointF& pos) const {
    const qreal ratio = devicePixelRatioF();
    return Graphic3d_Vec2i(static_cast<int>(pos.x() * ratio), static_cast<int>(pos.y() * ratio));
}

void OcctViewport::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    initViewer();
}

void OcctViewport::paintEvent(QPaintEvent* /*event*/) {
    if (m_view.IsNull()) {
        return;
    }
    FlushViewEvents(m_context, m_view, true);
}

void OcctViewport::resizeEvent(QResizeEvent* /*event*/) {
    if (!m_view.IsNull()) {
        m_view->MustBeResized();
        update();
    }
}

void OcctViewport::handleViewRedraw(const Handle(AIS_InteractiveContext)& context,
                                    const Handle(V3d_View)& view) {
    AIS_ViewController::handleViewRedraw(context, view);
    if (myToAskNextFrame) {
        update(); // keep animating (ViewCube camera transitions)
    }
}

void OcctViewport::mousePressEvent(QMouseEvent* event) {
    if (m_view.IsNull()) {
        return;
    }
    if (UpdateMouseButtons(toPixels(event->position()), toOcctButtons(event->buttons()),
                           toOcctModifiers(event->modifiers()), false)) {
        update();
    }
}

void OcctViewport::mouseReleaseEvent(QMouseEvent* event) {
    if (m_view.IsNull()) {
        return;
    }
    if (UpdateMouseButtons(toPixels(event->position()), toOcctButtons(event->buttons()),
                           toOcctModifiers(event->modifiers()), false)) {
        update();
    }
}

void OcctViewport::mouseMoveEvent(QMouseEvent* event) {
    if (m_view.IsNull()) {
        return;
    }
    if (UpdateMousePosition(toPixels(event->position()), toOcctButtons(event->buttons()),
                            toOcctModifiers(event->modifiers()), false)) {
        update();
    }
}

void OcctViewport::wheelEvent(QWheelEvent* event) {
    if (m_view.IsNull()) {
        return;
    }
    // Qt reports 1/8 degree units (120 per notch); OCCT zooms per degree.
    const double delta = event->angleDelta().y() / 8.0;
    if (UpdateZoom(Aspect_ScrollDelta(toPixels(event->position()), delta))) {
        update();
    }
}

} // namespace fission::viewer
