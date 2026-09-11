# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 FreeCAD contributors
# SPDX-FileNotice: Part of the FreeCAD project.

import FreeCAD
import Path
from Path.Post.ExportArray import (
    ArrayedOperation,
    all_cells,
    copy_count,
    count_tool_changes,
    default_mask,
    estimate_job_time,
    expand_operations,
    format_duration,
    format_job_time_estimate,
    is_cam_array_operation,
    is_enabled,
    mask_from_selected,
    mask_index,
    normalize_mask,
    parse_cycle_time_seconds,
    selected_cells,
)
from CAMTests.PathTestUtils import PathTestBase


class _FakeTC:
    def __init__(self, number):
        self.ToolNumber = number
        self.Label = f"T{number}"


class _FakeOp:
    def __init__(self, name, path, active=True, cycle="00:01:00", tool=None):
        self.Name = name
        self.Label = name
        self.Path = Path.Path([Path.Command(line) for line in path.split("\n") if line])
        self.Active = active
        self.ToolController = _FakeTC(tool) if tool is not None else None
        self.CoolantMode = "None"
        self.Placement = FreeCAD.Placement()
        self.Proxy = None
        self.TypeId = "Path::FeaturePython"
        self.InList = []
        self.CycleTime = cycle

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
        self.ToolChangeTime = kwargs.get("tool_change", 30)
        self.Path = Path.Path()
        self.Operations = type("Ops", (), {"Group": kwargs.get("ops", [])})()
        self.ExpressionEngine = []


class TestPathExportArray(PathTestBase):
    def test_mask_normalize_grows_with_ones(self):
        self.assertEqual(normalize_mask("10", 2, 2), "1011")
        self.assertEqual(normalize_mask("111111", 2, 1), "11")
        self.assertEqual(default_mask(3, 2), "111111")

    def test_mask_index_row_major(self):
        # 3 columns, cell (col 2, row 1) -> index 1*3+2 = 5
        self.assertEqual(mask_index(2, 1, 3), 5)

    def test_copies_and_offset_evaluate_expressions(self):
        from Path.Post.ExportArray import copies_x, copies_y, grid_x, grid_y, offset_vector

        class _Job:
            ExportArrayEnabled = True
            ExportArrayCountX = 0
            ExportArrayCountY = 0
            ExportArrayOffset = FreeCAD.Vector(0, 0, 0)
            ExpressionEngine = [
                ("ExportArrayCountX", "cx"),
                ("ExportArrayCountY", "cy"),
                ("ExportArrayOffset.x", "ox"),
                ("ExportArrayOffset.y", "oy"),
            ]

            def evalExpression(self, expr):
                return {"cx": 2, "cy": 1, "ox": 103.0, "oy": 52.0}[expr]

        job = _Job()
        self.assertEqual(copies_x(job), 2)
        self.assertEqual(copies_y(job), 1)
        self.assertEqual(grid_x(job), 3)
        self.assertEqual(grid_y(job), 2)
        off = offset_vector(job)
        self.assertRoughly(off.x, 103)
        self.assertRoughly(off.y, 52)

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

    def test_parse_and_format_cycle_time(self):
        self.assertEqual(parse_cycle_time_seconds("00:01:30"), 90)
        self.assertEqual(parse_cycle_time_seconds("1:02:03"), 3723)
        self.assertEqual(parse_cycle_time_seconds("1:05"), 65)
        self.assertEqual(parse_cycle_time_seconds("0"), 0)
        self.assertIsNone(parse_cycle_time_seconds("Tool Feedrate Error"))
        self.assertEqual(format_duration(90), "1:30")
        self.assertEqual(format_duration(3723), "1:02:03")

    def test_count_tool_changes_first_load_and_switches(self):
        mill = _FakeOp("Mill", "G1 X1", tool=1)
        mill2 = _FakeOp("Mill2", "G1 X2", tool=1)
        drill = _FakeOp("Drill", "G81 X1", tool=2)
        self.assertEqual(count_tool_changes([mill]), 1)
        self.assertEqual(count_tool_changes([mill, mill2]), 1)
        self.assertEqual(count_tool_changes([mill, mill2, drill]), 2)
        self.assertEqual(count_tool_changes([mill, drill, mill2]), 3)

    def test_estimate_job_time_multiplies_milling_not_tool_changes(self):
        mill = _FakeOp("Mill", "G1 X1", cycle="00:01:00", tool=1)
        drill = _FakeOp("Drill", "G81 X1", cycle="00:00:30", tool=2)
        job = _FakeJob(
            enabled=True,
            nx=1,
            ny=0,
            offset=FreeCAD.Vector(10, 0, 0),
            mask="11",
            tool_change=20,
            ops=[mill, drill],
        )
        est = estimate_job_time(job)
        # 2 ops × 2 parts: (60+30)*2 = 180s milling; 2 tool changes × 20s
        self.assertEqual(est["copies"], 2)
        self.assertEqual(est["operations"], 2)
        self.assertEqual(est["mill_seconds"], 180)
        self.assertEqual(est["tool_changes"], 2)
        self.assertEqual(est["tool_change_total"], 40)
        self.assertEqual(est["total_seconds"], 220)
        text = format_job_time_estimate(est)
        self.assertIn("3:40", text)
        self.assertIn("3:00", text)

    def test_estimate_job_time_without_array_is_one_copy(self):
        mill = _FakeOp("Mill", "G1 X1", cycle="00:02:00", tool=3)
        job = _FakeJob(enabled=False, nx=2, ny=2, ops=[mill], tool_change=15)
        est = estimate_job_time(job)
        self.assertEqual(copy_count(job), 1)
        self.assertEqual(est["mill_seconds"], 120)
        self.assertEqual(est["tool_changes"], 1)
        self.assertEqual(est["total_seconds"], 135)

    def test_estimate_job_time_no_selected_cells(self):
        mill = _FakeOp("Mill", "G1 X1", cycle="00:01:00", tool=1)
        job = _FakeJob(
            enabled=True,
            nx=1,
            ny=0,
            mask="00",
            ops=[mill],
        )
        est = estimate_job_time(job)
        self.assertEqual(est["copies"], 0)
        self.assertEqual(est["total_seconds"], 0)
        self.assertIn("—", format_job_time_estimate(est))
