#pragma once

#include "fission/features/BoxFeature.h"

#include <QDialog>

class QComboBox;
class QDoubleSpinBox;

namespace fission::ui {

class BoxDialog : public QDialog {
    Q_OBJECT

public:
    explicit BoxDialog(QWidget* parent = nullptr);

    [[nodiscard]] features::BoxFeature::Params params() const;

private:
    QDoubleSpinBox* m_dx;
    QDoubleSpinBox* m_dy;
    QDoubleSpinBox* m_dz;
    QDoubleSpinBox* m_x;
    QDoubleSpinBox* m_y;
    QDoubleSpinBox* m_z;
    QComboBox* m_operation;
};

} // namespace fission::ui
