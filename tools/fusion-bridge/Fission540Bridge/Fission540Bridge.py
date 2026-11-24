"""Fission540 bridge add-in for Fusion 360.

Commands (Utilities > Add-Ins panel):
  - Export to Fission540: writes the active design to a .f540x bundle.
  - Batch export project: writes every design in the active project to a folder,
    mirroring the project's folder structure.

Bundle format: docs/formats/f540x.md in the Fission540 repository.
"""

import os
import re
import traceback

import adsk.core
import adsk.fusion

from .f540x import exporter

CMD_EXPORT = "fission540BridgeExport"
CMD_BATCH = "fission540BridgeBatchExport"
PANEL_ID = "SolidScriptsAddinsPanel"

_app = None
_ui = None
_handlers = []  # Fusion drops event handlers that are not referenced from Python


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _add_command(CMD_EXPORT, "Export to Fission540",
                     "Export the active design to a Fission540 .f540x bundle.",
                     _ExportCreated())
        _add_command(CMD_BATCH, "Batch export project to Fission540",
                     "Export every design in the active project to .f540x bundles.",
                     _BatchCreated())
    except Exception:
        if _ui:
            _ui.messageBox("Fission540 bridge failed to start:\n" + traceback.format_exc())


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        for cmd_id in (CMD_EXPORT, CMD_BATCH):
            if panel:
                control = panel.controls.itemById(cmd_id)
                if control:
                    control.deleteMe()
            definition = _ui.commandDefinitions.itemById(cmd_id)
            if definition:
                definition.deleteMe()
        _handlers.clear()
    except Exception:
        if _ui:
            _ui.messageBox("Fission540 bridge failed to stop:\n" + traceback.format_exc())


def _add_command(cmd_id, name, tooltip, created_handler):
    definitions = _ui.commandDefinitions
    existing = definitions.itemById(cmd_id)
    if existing:
        existing.deleteMe()
    definition = definitions.addButtonDefinition(cmd_id, name, tooltip)
    definition.commandCreated.add(created_handler)
    _handlers.append(created_handler)
    panel = _ui.allToolbarPanels.itemById(PANEL_ID)
    if panel and not panel.controls.itemById(cmd_id):
        panel.controls.addCommand(definition)


def _safe_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "design"


# ---- Export active design -------------------------------------------------------

class _ExportCreated(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        handler = _ExportExecute()
        args.command.execute.add(handler)
        _handlers.append(handler)


class _ExportExecute(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _ui.messageBox("Open a design (Design workspace) first.")
                return
            dialog = _ui.createFileDialog()
            dialog.title = "Export to Fission540"
            dialog.filter = "Fission540 bundle (*.f540x)"
            dialog.initialFilename = _safe_filename(_app.activeDocument.name) + ".f540x"
            if dialog.showSave() != adsk.core.DialogResults.DialogOK:
                return
            path = dialog.filename
            if not path.lower().endswith(".f540x"):
                path += ".f540x"
            summary = exporter.export_design(_app, design, path)
            _ui.messageBox(summary.text(path), "Fission540 export")
        except Exception:
            _ui.messageBox("Export failed:\n" + traceback.format_exc())


# ---- Batch export -----------------------------------------------------------------

class _BatchCreated(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        handler = _BatchExecute()
        args.command.execute.add(handler)
        _handlers.append(handler)


def _collect_design_files(folder, prefix, out):
    for data_file in folder.dataFiles:
        if data_file.fileExtension.lower() == "f3d":
            out.append((prefix, data_file))
    for sub in folder.dataFolders:
        _collect_design_files(sub, os.path.join(prefix, _safe_filename(sub.name)), out)


class _BatchExecute(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            project = _app.data.activeProject
            if not project:
                _ui.messageBox("No active project.")
                return
            dialog = _ui.createFolderDialog()
            dialog.title = "Folder for exported .f540x bundles"
            if dialog.showDialog() != adsk.core.DialogResults.DialogOK:
                return
            out_root = os.path.join(dialog.folder, _safe_filename(project.name))

            files = []
            _collect_design_files(project.rootFolder, "", files)
            if not files:
                _ui.messageBox("No designs found in project " + project.name)
                return

            progress = _ui.createProgressDialog()
            progress.cancelButtonText = "Stop"
            progress.isBackgroundTranslucent = False
            progress.show("Fission540 batch export", "Exporting %v of %m", 0, len(files))

            done, failed, log = 0, [], []
            for i, (prefix, data_file) in enumerate(files):
                if progress.wasCancelled:
                    break
                progress.progressValue = i
                progress.message = "Exporting %v of %m: " + data_file.name
                adsk.doEvents()
                target_dir = os.path.join(out_root, prefix)
                os.makedirs(target_dir, exist_ok=True)
                target = os.path.join(target_dir, _safe_filename(data_file.name) + ".f540x")
                document = None
                try:
                    document = _app.documents.open(data_file, True)
                    design = adsk.fusion.Design.cast(
                        document.products.itemByProductType("DesignProductType"))
                    summary = exporter.export_design(_app, design, target)
                    done += 1
                    log.append("OK   %s (%d warnings)" % (os.path.join(prefix, data_file.name),
                                                         len(summary.warnings)))
                except Exception:
                    failed.append(data_file.name)
                    log.append("FAIL %s\n%s" % (os.path.join(prefix, data_file.name),
                                                traceback.format_exc()))
                finally:
                    if document:
                        try:
                            document.close(False)
                        except Exception:
                            pass
            progress.hide()

            os.makedirs(out_root, exist_ok=True)
            with open(os.path.join(out_root, "batch-export.log"), "w", encoding="utf-8") as f:
                f.write("\n".join(log) + "\n")
            text = "Exported %d of %d designs to\n%s" % (done, len(files), out_root)
            if failed:
                text += "\n\nFailed (%d): %s\nSee batch-export.log." % (len(failed), ", ".join(failed[:10]))
            _ui.messageBox(text, "Fission540 batch export")
        except Exception:
            _ui.messageBox("Batch export failed:\n" + traceback.format_exc())
