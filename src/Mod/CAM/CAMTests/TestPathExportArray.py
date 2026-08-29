# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 FreeCAD contributors
# SPDX-FileNotice: Part of the FreeCAD project.

import FreeCAD
import Path
from Path.Post.ExportArray import (
    ArrayedOperation,
    all_cells,
    default_mask,
    expand_operations,
    is_cam_array_operation,
    is_enabled,
    mask_from_selected,
    mask_index,
    normalize_mask,
    selected_cells,
)
from CAMTests.PathTestUtils import PathTestBase


class _FakeOp:
    def __init__(self, name, path, active=True):
        self.Name = name
        self.Label = name
        self.Path = Path.Path([Path.Command(line) for line in path.split("\n") if line])
        self.Active = active
        self.ToolController = None
        self.CoolantMode = "None"
        self.Placement = FreeCAD.Placement()
        self.Proxy = None
        self.TypeId = "Path::FeaturePython"
        self.InList = []

    def isDerivedFrom(self, typ):
        return typ in ("Path::Feature", "Path::FeaturePython")


class ObjectArray:
    """Stand-in for Path.Op.Gui.Array.ObjectArray."""


class _FakeArrayOp(_FakeOp):
    def __init__(self, name, base):
        super().__init__(name, "G0 X0 Y0")
        self.Base = [base]
        self.Proxy = ObjectArray()


class _FakeJob:
    def __init__(self, **kwargs):
        self.ExportArrayEnabled = kwargs.get("enabled", False)
        # nx/ny are extra copies (CAM Array CopiesX/Y)
        self.ExportArrayCountX = kwargs.get("nx", 0)
        self.ExportArrayCountY = kwargs.get("ny", 0)
        self.ExportArrayOffset = kwargs.get("offset", FreeCAD.Vector(10, 20, 0))
        self.ExportArraySwapDirection = kwargs.get("swap", False)
        self.ExportArrayMask = kwargs.get("mask", "")
        self.Path = Path.Path()
        self.Operations = type("Ops", (), {"Group": kwargs.get("ops", [])})()


class TestPathExportArray(PathTestBase):
    def test_mask_normalize_grows_with_ones(self):
        self.assertEqual(normalize_mask("10", 2, 2), "1011")
        self.assertEqual(normalize_mask("111111", 2, 1), "11")
        self.assertEqual(default_mask(3, 2), "111111")

    def test_mask_index_row_major(self):
        # 3 columns, cell (col 2, row 1) -> index 1*3+2 = 5
        self.assertEqual(mask_index(2, 1, 3), 5)

    def test_is_enabled_requires_grid(self):
        self.assertFalse(is_enabled(_FakeJob(enabled=True, nx=0, ny=0)))
        self.assertTrue(is_enabled(_FakeJob(enabled=True, nx=1, ny=0)))
        self.assertFalse(is_enabled(_FakeJob(enabled=False, nx=2, ny=2)))

    def test_all_cells_column_major_default(self):
        # 1 extra copy in X and Y → 2×2 grid
        job = _FakeJob(enabled=True, nx=1, ny=1, offset=FreeCAD.Vector(10, 20, 0), swap=False)
        cells = all_cells(job)
        coords = [(ix, iy, (off.x, off.y)) for ix, iy, off in cells]
        self.assertEqual(
            coords,
            [
                (0, 0, (0.0, 0.0)),
                (0, 1, (0.0, 20.0)),
                (1, 0, (10.0, 0.0)),
                (1, 1, (10.0, 20.0)),
            ],
        )

    def test_all_cells_row_major_when_swapped(self):
        job = _FakeJob(enabled=True, nx=1, ny=1, offset=FreeCAD.Vector(10, 20, 0), swap=True)
        coords = [(ix, iy) for ix, iy, _off in all_cells(job)]
        self.assertEqual(coords, [(0, 0), (1, 0), (0, 1), (1, 1)])

    def test_selected_cells_third_column_only(self):
        # 2 extra X + 1 extra Y → 3 columns × 2 rows; keep column 3 (ix=2)
        job = _FakeJob(
            enabled=True,
            nx=2,
            ny=1,
            offset=FreeCAD.Vector(100, 50, 0),
            mask=mask_from_selected(_FakeJob(nx=2, ny=1), [(2, 0), (2, 1)]),
        )
        selected = selected_cells(job)
        self.assertEqual([(ix, iy) for ix, iy, _ in selected], [(2, 0), (2, 1)])
        self.assertRoughly(selected[0][2].x, 200)
        self.assertRoughly(selected[0][2].y, 0)
        self.assertRoughly(selected[1][2].y, 50)

    def test_selected_single_cell(self):
        job = _FakeJob(
            enabled=True,
            nx=2,
            ny=1,
            offset=FreeCAD.Vector(100, 50, 0),
            mask=mask_from_selected(_FakeJob(nx=2, ny=1), [(1, 0)]),
        )
        selected = selected_cells(job)
        self.assertEqual([(ix, iy) for ix, iy, _ in selected], [(1, 0)])

    def test_expand_operation_order_then_cells(self):
        mill = _FakeOp("Mill", "G0 X0 Y0\nG1 X5 Y0")
        drill = _FakeOp("Drill", "G0 X1 Y1\nG81 X1 Y1 Z-2")
        job = _FakeJob(
            enabled=True,
            nx=1,
            ny=0,
            offset=FreeCAD.Vector(10, 0, 0),
            mask="11",
        )
        cells = selected_cells(job)
        expanded = expand_operations([mill, drill], job, cells)
        labels = [op.Label for op in expanded]
        self.assertEqual(labels, ["Mill [1,1]", "Mill [2,1]", "Drill [1,1]", "Drill [2,1]"])

        mill1 = [c for c in expanded[1].Path.Commands if c.Name.startswith("G")][0]
        self.assertRoughly(mill1.x, 10.0)

    def test_expand_skips_cam_array_and_inactive(self):
        mill = _FakeOp("Mill", "G0 X0 Y0")
        array = _FakeArrayOp("Array", mill)
        inactive = _FakeOp("Old", "G0 X9 Y9", active=False)
        self.assertTrue(is_cam_array_operation(array))
        self.assertFalse(is_cam_array_operation(mill))

        job = _FakeJob(enabled=True, nx=1, ny=0, offset=FreeCAD.Vector(10, 0, 0), mask="11")
        expanded = expand_operations([mill, array, inactive], job)
        self.assertEqual([op.Label for op in expanded], ["Mill [1,1]", "Mill [2,1]"])

    def test_apply_to_processor_uses_mask_without_prompt(self):
        from Path.Post.ExportArray import apply_to_processor

        mill = _FakeOp("Mill", "G0 X0 Y0\nG1 X1 Y0")
        job = _FakeJob(
            enabled=True,
            nx=1,
            ny=0,
            offset=FreeCAD.Vector(10, 0, 0),
            mask="01",
        )

        class _Proc:
            def __init__(self):
                self._job = job
                self._operations = [mill]

        proc = _Proc()
        self.assertTrue(apply_to_processor(proc, prompt=False))
        self.assertEqual(len(proc._operations), 1)
        self.assertEqual(proc._operations[0].Label, "Mill [2,1]")
        self.assertTrue(apply_to_processor(proc, prompt=False))  # idempotent
        self.assertEqual(len(proc._operations), 1)

    def test_preview_path_omits_origin(self):
        from Path.Post.ExportArray import build_preview_path, update_preview

        mill = _FakeOp("Mill", "G0 X0 Y0\nG1 X1 Y0")
        job = _FakeJob(
            enabled=True,
            nx=1,
            ny=0,
            offset=FreeCAD.Vector(10, 0, 0),
            mask="11",
            ops=[mill],
        )
        path = build_preview_path(job)
        xs = [c.x for c in path.Commands if c.x is not None]
        self.assertTrue(xs)
        self.assertTrue(all(x >= 9.0 for x in xs))
        update_preview(job)
        self.assertTrue(job.Path.Commands)

    def test_preview_path_respects_mask(self):
        from Path.Post.ExportArray import build_preview_path

        mill = _FakeOp("Mill", "G0 X0 Y0\nG1 X1 Y0")
        # only origin selected → no extra copies in preview
        job = _FakeJob(
            enabled=True,
            nx=1,
            ny=0,
            offset=FreeCAD.Vector(10, 0, 0),
            mask="10",
            ops=[mill],
        )
        self.assertFalse(build_preview_path(job).Commands)
        # only extra copy selected
        job.ExportArrayMask = "01"
        xs = [c.x for c in build_preview_path(job).Commands if c.x is not None]
        self.assertTrue(xs)
        self.assertTrue(all(x >= 9.0 for x in xs))

    def test_arrayed_operation_translates_moves(self):
        op = _FakeOp("Pocket", "G0 X1 Y2 Z3\nG1 X4 Y5 Z3")
        arrayed = ArrayedOperation(op, 1, 2, FreeCAD.Vector(10, 20, 0))
        xs = [c.x for c in arrayed.Path.Commands if c.x is not None]
        ys = [c.y for c in arrayed.Path.Commands if c.y is not None]
        self.assertRoughly(xs[0], 11)
        self.assertRoughly(ys[0], 22)
        self.assertRoughly(xs[1], 14)
        self.assertRoughly(ys[1], 25)
