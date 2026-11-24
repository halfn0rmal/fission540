#include "fission/ui/BoxDialog.h"

#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>

namespace fission::ui {
namespace {

QDoubleSpinBox* makeLength(double value, double minimum) {
    auto* box = new QDoubleSpinBox();
    box->setRange(minimum, 1.0e6);
    box->setDecimals(3);
    box->setSuffix(" mm");
    box->setValue(value);
    return box;
}

} // namespace

BoxDialog::BoxDialog(QWidget* parent)
    : QDialog(parent), m_dx(makeLength(20.0, 0.001)), m_dy(makeLength(20.0, 0.001)),
      m_dz(makeLength(20.0, 0.001)), m_x(makeLength(0.0, -1.0e6)), m_y(makeLength(0.0, -1.0e6)),
      m_z(makeLength(0.0, -1.0e6)), m_operation(new QComboBox()) {
    setWindowTitle(tr("Box"));

    m_operation->addItem(tr("Join"), static_cast<int>(features::BodyOperation::Join));
    m_operation->addItem(tr("Cut"), static_cast<int>(features::BodyOperation::Cut));
    m_operation->addItem(tr("Intersect"), static_cast<int>(features::BodyOperation::Intersect));

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);

    auto* form = new QFormLayout(this);
    form->addRow(tr("Length (X)"), m_dx);
    form->addRow(tr("Width (Y)"), m_dy);
    form->addRow(tr("Height (Z)"), m_dz);
    form->addRow(tr("Origin X"), m_x);
    form->addRow(tr("Origin Y"), m_y);
    form->addRow(tr("Origin Z"), m_z);
    form->addRow(tr("Operation"), m_operation);
    form->addRow(buttons);
}

features::BoxFeature::Params BoxDialog::params() const {
    features::BoxFeature::Params p;
    p.dx = m_dx->value();
    p.dy = m_dy->value();
    p.dz = m_dz->value();
    p.origin = {m_x->value(), m_y->value(), m_z->value()};
    p.operation = static_cast<features::BodyOperation>(m_operation->currentData().toInt());
    return p;
}

} // namespace fission::ui
