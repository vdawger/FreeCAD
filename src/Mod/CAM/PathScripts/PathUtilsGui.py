# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2019 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import FreeCADGui
import FreeCAD
import Path
import Path.Main.Gui.JobCmd as PathJobCmd
import Path.Main.Job as PathJob
import Path.Tool.Controller as PathToolController
import PathScripts.PathUtils as PathUtils

if False:
    Path.Log.setLevel(Path.Log.Level.DEBUG, Path.Log.thisModule())
    Path.Log.trackModule(Path.Log.thisModule())
else:
    Path.Log.setLevel(Path.Log.Level.INFO, Path.Log.thisModule())

translate = FreeCAD.Qt.translate


def _notify(message):
    """Say what was picked instead of asking. Report view plus status bar."""
    FreeCAD.Console.PrintMessage(message + "\n")
    try:
        FreeCADGui.getMainWindow().statusBar().showMessage(message, 10000)
    except Exception:
        pass


def _jobInEdit(jobs):
    """The job of whatever is open in a task panel, if it is one of jobs."""
    try:
        gui_doc = FreeCADGui.ActiveDocument
        editing = gui_doc.getInEdit() if gui_doc else None
        obj = getattr(editing, "Object", None) if editing else None
        job = PathUtils.findParentJob(obj) if obj else None
    except Exception:
        job = None
    return job if job in jobs else None


class PathUtilsUserInput(object):
    """GUI answers for PathUtils. Ambiguous choices get a default instead of a
    modal dialog; the choice is reported and can be changed afterwards."""

    def __init__(self):
        self._lastJobName = None

    def rememberJob(self, job):
        if job is not None:
            self._lastJobName = (job.Document.Name, job.Name)

    def _lastJob(self, jobs):
        if self._lastJobName is None:
            return None
        for job in jobs:
            if (job.Document.Name, job.Name) == self._lastJobName:
                return job
        return None

    def selectedToolController(self):
        tc = None
        # check if a user has selected a tool controller in the tree.
        # Return the first one and remove all from selection
        for sel in FreeCADGui.Selection.getSelectionEx():
            if hasattr(sel.Object, "Proxy"):
                if isinstance(sel.Object.Proxy, PathToolController.ToolController):
                    if tc is None:
                        tc = sel.Object
                    FreeCADGui.Selection.removeSelection(sel.Object)
        return tc

    def chooseToolController(self, controllers):
        """Use the controller of the job's latest operation, else the first one.
        The operation's Tool Controller field changes it later."""
        tc = controllers[0]
        try:
            job = PathUtils.findParentJob(controllers[0])
            ops = list(job.Operations.Group) if job else []
        except Exception:
            ops = []
        for op in reversed(ops):
            used = getattr(op, "ToolController", None)
            if used in controllers:
                tc = used
                break
        _notify(
            translate(
                "Path",
                "Using tool controller {}. Change it in the operation's Tool Controller field.",
            ).format(tc.Label)
        )
        return tc

    def chooseJob(self, jobs):
        selected = FreeCADGui.Selection.getSelection()

        jbs = [
            sel
            for sel in selected
            if hasattr(sel, "Proxy") and isinstance(sel.Proxy, PathJob.ObjectJob)
        ]
        if len(jbs) == 1:  # selection contains one Job object
            return self._picked(jbs[0])

        if len(selected) == 1:  # selection contains only one object
            found = PathUtils.findParentJob(selected[0])
            if found:
                return self._picked(found)

        jbs = [j for j in jobs if all(o in j.Model.Group for o in selected)]
        if len(jbs) == 1:  # all selected objects inside Model group of one Job
            return self._picked(jbs[0])

        jbs = [j for j in jobs if all(o in j.Proxy.baseObjects(j) for o in selected)]
        if len(jbs) == 1:  # all selected objects has a clone inside one Job
            return self._picked(jbs[0])

        # Still ambiguous: no dialog. Prefer the job open for editing, then the
        # job used last, then the newest job.
        candidates = jbs or jobs
        job = _jobInEdit(candidates) or self._lastJob(candidates) or candidates[-1]
        if len(jobs) > 1:
            _notify(
                translate(
                    "Path",
                    "Added to {}. To use another job, select it or its model first.",
                ).format(job.Label)
            )
        return self._picked(job)

    def _picked(self, job):
        self.rememberJob(job)
        return job

    def createJob(self):
        return PathJobCmd.CommandJobCreate().Activated()


PathUtils.UserInput = PathUtilsUserInput()
