# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 FreeCAD contributors
# SPDX-FileNotice: Part of the FreeCAD project.

"""Checkbox grid for export-array cells. Embedded in the Job panel."""

import FreeCAD
from PySide import QtCore, QtGui
from Path.Post import ExportArray

translate = FreeCAD.Qt.translate


class ExportArrayCellGrid(QtGui.QWidget):
    """Live cell picker. Origin is bottom-left. Emits maskChanged on edits."""

    maskChanged = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job = None
        self._nx = 0
        self._ny = 0
        self._boxes = {}
        self._updating = False

        layout = QtGui.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._hint = QtGui.QLabel(
            translate(
                "CAM_Job",
                "Checked cells are shown in the 3D view and posted. "
                "Origin (1,1) is bottom-left.",
            )
        )
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._grid_host = QtGui.QWidget()
        self._grid = QtGui.QGridLayout(self._grid_host)
        self._grid.setSpacing(4)
        layout.addWidget(self._grid_host)

        btns = QtGui.QHBoxLayout()
        all_btn = QtGui.QPushButton(translate("CAM_Job", "All"))
        none_btn = QtGui.QPushButton(translate("CAM_Job", "None"))
        invert_btn = QtGui.QPushButton(translate("CAM_Job", "Invert"))
        all_btn.clicked.connect(self.select_all)
        none_btn.clicked.connect(self.select_none)
        invert_btn.clicked.connect(self.invert)
        btns.addWidget(all_btn)
        btns.addWidget(none_btn)
        btns.addWidget(invert_btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        self._count_label = QtGui.QLabel()
        layout.addWidget(self._count_label)

    def configure(self, job):
        self._job = job
        nx = ExportArray.grid_x(job)
        ny = ExportArray.grid_y(job)
        if (nx, ny) != (self._nx, self._ny):
            self._nx = nx
            self._ny = ny
            self._rebuild()
        self._apply_mask(getattr(job, "ExportArrayMask", ""))
        self._refresh_tooltips()
        self._update_count()

    def mask(self):
        if not self._job:
            return ""
        return ExportArray.mask_from_selected(self._job, self._selected_xy())

    def _clear_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._boxes = {}

    def _rebuild(self):
        self._clear_grid()
        for ix in range(self._nx):
            hdr = QtGui.QPushButton(translate("CAM_Job", "Col {n}").format(n=ix + 1))
            hdr.setFlat(True)
            hdr.clicked.connect(lambda checked=False, c=ix: self._toggle_column(c))
            self._grid.addWidget(hdr, 0, ix + 1)

        for iy in range(self._ny):
            layout_row = self._ny - iy
            row_hdr = QtGui.QPushButton(translate("CAM_Job", "Row {n}").format(n=iy + 1))
            row_hdr.setFlat(True)
            row_hdr.clicked.connect(lambda checked=False, r=iy: self._toggle_row(r))
            self._grid.addWidget(row_hdr, layout_row, 0)
            for ix in range(self._nx):
                box = QtGui.QCheckBox(f"{ix + 1},{iy + 1}")
                box.setMinimumSize(48, 32)
                box.stateChanged.connect(self._on_box_changed)
                self._boxes[(ix, iy)] = box
                self._grid.addWidget(box, layout_row, ix + 1)

    def _refresh_tooltips(self):
        if not self._job:
            return
        off = ExportArray.offset_vector(self._job)
        for (ix, iy), box in self._boxes.items():
            box.setToolTip(
                translate(
                    "CAM_Job",
                    "Column {c}, Row {r}\nOffset: X {x:.3f}, Y {y:.3f}",
                ).format(c=ix + 1, r=iy + 1, x=off.x * ix, y=off.y * iy)
            )

    def _apply_mask(self, mask):
        if not self._nx or not self._ny:
            return
        mask = ExportArray.normalize_mask(mask, self._nx, self._ny)
        self._updating = True
        for iy in range(self._ny):
            for ix in range(self._nx):
                on = mask[ExportArray.mask_index(ix, iy, self._nx)] == "1"
                box = self._boxes.get((ix, iy))
                if box:
                    box.setChecked(on)
        self._updating = False

    def _selected_xy(self):
        return [(ix, iy) for (ix, iy), box in self._boxes.items() if box.isChecked()]

    def _on_box_changed(self):
        if self._updating:
            return
        self._update_count()
        self.maskChanged.emit(self.mask())

    def _set_all(self, state):
        self._updating = True
        for box in self._boxes.values():
            box.setChecked(state)
        self._updating = False
        self._on_box_changed()

    def select_all(self):
        self._set_all(True)

    def select_none(self):
        self._set_all(False)

    def invert(self):
        self._updating = True
        for box in self._boxes.values():
            box.setChecked(not box.isChecked())
        self._updating = False
        self._on_box_changed()

    def _toggle_column(self, ix):
        boxes = [self._boxes[(ix, iy)] for iy in range(self._ny) if (ix, iy) in self._boxes]
        if not boxes:
            return
        turn_on = not all(b.isChecked() for b in boxes)
        self._updating = True
        for b in boxes:
            b.setChecked(turn_on)
        self._updating = False
        self._on_box_changed()

    def _toggle_row(self, iy):
        boxes = [self._boxes[(ix, iy)] for ix in range(self._nx) if (ix, iy) in self._boxes]
        if not boxes:
            return
        turn_on = not all(b.isChecked() for b in boxes)
        self._updating = True
        for b in boxes:
            b.setChecked(turn_on)
        self._updating = False
        self._on_box_changed()

    def _update_count(self):
        n = len(self._selected_xy())
        total = self._nx * self._ny
        self._count_label.setText(
            translate("CAM_Job", "{n} of {total} cells selected").format(n=n, total=total)
        )
