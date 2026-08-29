# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 FreeCAD contributors
# SPDX-FileNotice: Part of the FreeCAD project.

"""Job-level export array: one grid applied to every operation at post time.

Unlike CAM Array (which wraps each operation separately), this expands each
active operation across selected grid cells *in operation order*:

    for operation in job:
        for selected cell:
            emit operation translated to that cell

Existing CAM Array operations are skipped while this is enabled so the base
operations are not posted twice.
"""

import FreeCAD
import Path
import Path.Base.Util as PathUtil
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

_GROUP = "Export Array"


def ensure_job_properties(obj):
    """Add export-array properties to a Job if they are missing."""
    if not hasattr(obj, "addProperty"):
        return

    if not hasattr(obj, "ExportArrayEnabled"):
        obj.addProperty(
            "App::PropertyBool",
            "ExportArrayEnabled",
            _GROUP,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "When True, Post Process arrays every operation across a grid "
                "and asks which cells to include",
            ),
        )
        obj.ExportArrayEnabled = False

    if not hasattr(obj, "ExportArrayCountX"):
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "ExportArrayCountX",
            _GROUP,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Extra copies in X (same as CAM Array CopiesX). "
                "Total columns = this value + 1",
            ),
        )
        obj.ExportArrayCountX = (0, 0, 999, 1)

    if not hasattr(obj, "ExportArrayCountY"):
        obj.addProperty(
            "App::PropertyIntegerConstraint",
            "ExportArrayCountY",
            _GROUP,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Extra copies in Y (same as CAM Array CopiesY). "
                "Total rows = this value + 1",
            ),
        )
        obj.ExportArrayCountY = (0, 0, 999, 1)

    if not hasattr(obj, "ExportArrayOffset"):
        obj.addProperty(
            "App::PropertyVectorDistance",
            "ExportArrayOffset",
            _GROUP,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Spacing between neighbouring cells (X = column pitch, Y = row pitch)",
            ),
        )
        obj.ExportArrayOffset = FreeCAD.Vector(0, 0, 0)

    if not hasattr(obj, "ExportArraySwapDirection"):
        obj.addProperty(
            "App::PropertyBool",
            "ExportArraySwapDirection",
            _GROUP,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "If False, walk Y then X (column by column). If True, walk X then Y "
                "(row by row). Matches CAM Array SwapDirection.",
            ),
        )
        obj.ExportArraySwapDirection = False

    if not hasattr(obj, "ExportArrayMask"):
        obj.addProperty(
            "App::PropertyString",
            "ExportArrayMask",
            _GROUP,
            QT_TRANSLATE_NOOP(
                "App::Property",
                "Which cells to post: a string of 0/1, row-major from the origin "
                "(index = row * columns + column, columns = CountX + 1)",
            ),
        )
        obj.ExportArrayMask = default_mask(1, 1)
        obj.setEditorMode("ExportArrayMask", 2)

    _sync_editor_modes(obj)
    new_mask = normalize_mask(
        getattr(obj, "ExportArrayMask", ""),
        grid_x(obj),
        grid_y(obj),
    )
    if getattr(obj, "ExportArrayMask", None) != new_mask:
        obj.ExportArrayMask = new_mask


def _sync_editor_modes(obj):
    if not hasattr(obj, "ExportArrayEnabled") or not hasattr(obj, "setEditorMode"):
        return
    hidden = 0 if obj.ExportArrayEnabled else 2
    for prop in (
        "ExportArrayCountX",
        "ExportArrayCountY",
        "ExportArrayOffset",
        "ExportArraySwapDirection",
    ):
        if hasattr(obj, prop):
            obj.setEditorMode(prop, hidden)
    if hasattr(obj, "ExportArrayMask"):
        obj.setEditorMode("ExportArrayMask", 2)


def copies_x(job):
    """Extra copies in X (CAM Array CopiesX)."""
    return max(0, int(getattr(job, "ExportArrayCountX", 0) or 0))


def copies_y(job):
    """Extra copies in Y (CAM Array CopiesY)."""
    return max(0, int(getattr(job, "ExportArrayCountY", 0) or 0))


def grid_x(job):
    """Total columns including the original."""
    return copies_x(job) + 1


def grid_y(job):
    """Total rows including the original."""
    return copies_y(job) + 1


def count_x(job):
    """Total columns. Kept as an alias for dialog/mask helpers."""
    return grid_x(job)


def count_y(job):
    return grid_y(job)


def offset_vector(job):
    off = getattr(job, "ExportArrayOffset", None)
    if off is None:
        return FreeCAD.Vector(0, 0, 0)
    return FreeCAD.Vector(off.x, off.y, off.z)


def default_mask(nx, ny):
    return "1" * (max(1, nx) * max(1, ny))


def normalize_mask(mask, nx, ny):
    n = max(1, nx) * max(1, ny)
    bits = "".join("1" if c != "0" else "0" for c in (mask or ""))
    if len(bits) < n:
        bits += "1" * (n - len(bits))
    return bits[:n]


def mask_index(ix, iy, nx):
    return iy * nx + ix


def is_enabled(job):
    if not job or not getattr(job, "ExportArrayEnabled", False):
        return False
    return copies_x(job) > 0 or copies_y(job) > 0


def is_cam_array_operation(obj):
    """True for Path Modification Array (CAM_Array), not Array dressups."""
    proxy = getattr(obj, "Proxy", None)
    return type(proxy).__name__ == "ObjectArray"


def cell_offset(job, ix, iy):
    off = offset_vector(job)
    return FreeCAD.Vector(off.x * ix, off.y * iy, off.z * iy)


def all_cells(job):
    """All grid cells as (ix, iy, offset), in posting order."""
    nx = count_x(job)
    ny = count_y(job)
    swap = bool(getattr(job, "ExportArraySwapDirection", False))
    cells = []
    if swap:
        for iy in range(ny):
            for ix in range(nx):
                cells.append((ix, iy, cell_offset(job, ix, iy)))
    else:
        for ix in range(nx):
            for iy in range(ny):
                cells.append((ix, iy, cell_offset(job, ix, iy)))
    return cells


def selected_cells(job):
    nx = count_x(job)
    ny = count_y(job)
    mask = normalize_mask(getattr(job, "ExportArrayMask", ""), nx, ny)
    return [
        (ix, iy, offset)
        for ix, iy, offset in all_cells(job)
        if mask[mask_index(ix, iy, nx)] == "1"
    ]


def set_mask(job, mask):
    job.ExportArrayMask = normalize_mask(mask, count_x(job), count_y(job))


def mask_from_selected(job, selected_xy):
    nx = count_x(job)
    ny = count_y(job)
    bits = ["0"] * (nx * ny)
    for ix, iy in selected_xy:
        if 0 <= ix < nx and 0 <= iy < ny:
            bits[mask_index(ix, iy, nx)] = "1"
    return "".join(bits)


class ArrayedOperation:
    """Stand-in operation: source path translated to one array cell."""

    def __init__(self, source, ix, iy, offset):
        import PathScripts.PathUtils as PathUtils

        self.source = source
        self.ArrayIndexX = ix
        self.ArrayIndexY = iy
        src_label = getattr(source, "Label", "Op")
        src_name = getattr(source, "Name", "Op")
        self.Label = f"{src_label} [{ix + 1},{iy + 1}]"
        self.Name = f"{src_name}_{ix}_{iy}"
        self.Active = True
        self.Placement = FreeCAD.Placement()
        self.ToolController = PathUtil.toolControllerForOp(source)
        self.CoolantMode = PathUtil.coolantModeForOp(source)
        self.Proxy = getattr(source, "Proxy", None)
        self.TypeId = getattr(source, "TypeId", "Path::FeaturePython")
        self.InList = getattr(source, "InList", [])

        src_path = PathUtils.getPathWithPlacement(source)
        if hasattr(src_path, "copy"):
            copied = src_path.copy()
        else:
            copied = Path.Path(list(src_path.Commands))

        if offset.Length > 1e-12:
            pl = FreeCAD.Placement()
            pl.move(offset)
            self.Path = PathUtils.applyPlacementToPath(pl, copied)
        else:
            self.Path = copied

    def isDerivedFrom(self, typ):
        return typ in ("Path::Feature", "Path::FeaturePython", self.TypeId)


def expand_operations(operations, job, cells=None):
    """Replace operations with per-cell copies, skipping CAM Array wrappers.

    CAM Array objects are skipped when the job still contains the base
    operations they wrap. If the job only contains Array objects, they are
    kept so posting does not go empty.
    """
    if cells is None:
        cells = selected_cells(job)
    active = [op for op in operations if PathUtil.activeForOp(op)]
    bases = [op for op in active if not is_cam_array_operation(op)]
    sources = bases if bases else active
    expanded = []
    for op in sources:
        for ix, iy, offset in cells:
            expanded.append(ArrayedOperation(op, ix, iy, offset))
    return expanded


def apply_to_processor(processor, prompt=None):
    """Expand processor._operations from the job's saved cell mask.

    ``prompt`` is ignored; cell selection lives on the Job panel.
    Returns False if the mask selects no cells.
    """
    job = getattr(processor, "_job", None)
    if not is_enabled(job):
        return True
    if getattr(processor, "_export_array_applied", False):
        return True

    ensure_job_properties(job)

    cells = selected_cells(job)
    if not cells:
        Path.Log.warning(translate("CAM_Post", "No export-array cells selected"))
        return False

    processor._operations = expand_operations(processor._operations, job, cells)
    processor._export_array_applied = True
    Path.Log.debug(
        f"Export array: {len(cells)} cells, {len(processor._operations)} expanded operations"
    )
    return True


def _preview_sources(job):
    ops = getattr(getattr(job, "Operations", None), "Group", None) or []
    active = [op for op in ops if PathUtil.activeForOp(op)]
    return [op for op in active if not is_cam_array_operation(op)]


def origin_selected(job):
    nx = grid_x(job)
    mask = normalize_mask(getattr(job, "ExportArrayMask", ""), nx, grid_y(job))
    return mask[mask_index(0, 0, nx)] == "1"


def _sync_origin_visibility(job):
    """Hide base op paths when origin cell is unchecked so 3D matches export."""
    if not FreeCAD.GuiUp:
        return
    proxy = getattr(job, "Proxy", None)
    hid = getattr(proxy, "_exportArrayHidOps", None) if proxy else None
    if hid is None:
        hid = {}

    show_origin = (not is_enabled(job)) or origin_selected(job)
    if not show_origin:
        for op in _preview_sources(job):
            vo = getattr(op, "ViewObject", None)
            if vo is None:
                continue
            if op.Name not in hid:
                hid[op.Name] = bool(vo.Visibility)
            vo.Visibility = False
        if proxy is not None:
            proxy._exportArrayHidOps = hid
        return

    for op in _preview_sources(job):
        vo = getattr(op, "ViewObject", None)
        if vo is None:
            continue
        if op.Name in hid:
            vo.Visibility = hid[op.Name]
    if proxy is not None:
        proxy._exportArrayHidOps = {}


def build_preview_path(job):
    """Toolpath for selected extra copies (origin is drawn by each operation)."""
    commands = []
    for op in _preview_sources(job):
        for ix, iy, offset in selected_cells(job):
            if ix == 0 and iy == 0:
                continue
            arrayed = ArrayedOperation(op, ix, iy, offset)
            if arrayed.Path and arrayed.Path.Commands:
                commands.extend(arrayed.Path.Commands)
    return Path.Path(commands)


def update_preview(job):
    """Show extra array copies on the Job's Path in the 3D view."""
    if not job or not hasattr(job, "Path"):
        return
    try:
        center = job.Path.Center if job.Path else None
        if not is_enabled(job):
            if getattr(job.Path, "Commands", None):
                job.Path = Path.Path()
                if center:
                    job.Path.Center = center
            _sync_origin_visibility(job)
            return
        job.Path = build_preview_path(job)
        if center:
            job.Path.Center = center
        _sync_origin_visibility(job)
    except Exception as e:
        Path.Log.error(f"Export array preview failed: {e}")
