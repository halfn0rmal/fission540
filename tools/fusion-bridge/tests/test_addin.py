"""Loads the add-in itself the way Fusion does, and runs its import command's work.

This is the file Fusion executes first, so it is worth knowing that it imports, that
`run()` registers all three commands, and that the import command's helper handles both
a good bundle and a file that is not one — none of which needs Fusion.
"""

import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Fusion loads the add-in's folder as a package, so `Fission540Bridge.py` can use
# relative imports. That only works if the folder's *parent* is what is on the path:
# with the folder itself on the path the file loads as a top-level module instead and
# its relative imports fail. Another test module may have put it there for `f540x`, so
# move it to the end rather than assuming an import order.
PARENT = os.path.normpath(os.path.join(HERE, ".."))
ADDIN_DIR = os.path.join(PARENT, "Fission540Bridge")
while ADDIN_DIR in sys.path:
    sys.path.remove(ADDIN_DIR)
sys.path.insert(0, PARENT)

import fusion_mock  # noqa: E402

fusion_mock.install()

from Fission540Bridge import Fission540Bridge as addin  # noqa: E402
from Fission540Bridge.f540x import exporter  # noqa: E402

sys.path.append(ADDIN_DIR)  # back for the test modules that import f540x directly


class AddInTest(unittest.TestCase):
    def setUp(self):
        self.app = fusion_mock.FakeApp()
        fusion_mock.Application.current = self.app
        addin._app = self.app
        addin._ui = self.app.userInterface
        addin._handlers.clear()

    def test_run_registers_the_three_commands(self):
        addin.run(None)
        definitions = self.app.userInterface.commandDefinitions.items
        self.assertEqual(sorted(definitions),
                         sorted([addin.CMD_BATCH, addin.CMD_EXPORT, addin.CMD_IMPORT]))
        self.assertEqual(definitions[addin.CMD_IMPORT].name, "Import from Fission540")
        panel = self.app.userInterface.allToolbarPanels.itemById(addin.PANEL_ID)
        self.assertIn(addin.CMD_IMPORT, panel.controls.items)
        self.assertEqual(self.app.userInterface.messages, [])  # nothing went wrong

    def test_stop_removes_them_again(self):
        addin.run(None)
        addin.stop(None)
        panel = self.app.userInterface.allToolbarPanels.itemById(addin.PANEL_ID)
        self.assertTrue(all(control.deleted for control in panel.controls.items.values()))
        self.assertEqual(self.app.userInterface.messages, [])

    def test_import_one_rebuilds_a_bundle_and_cleans_up(self):
        exporting_app = types.SimpleNamespace(version="2.0.test", activeDocument=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "AshTray.f540x")
            exporter.export_design(exporting_app, fusion_mock.make_design(), path)
            before = set(os.listdir(tempfile.gettempdir()))
            text = addin._import_one(path)
            after = set(os.listdir(tempfile.gettempdir()))
            self.assertIn("Imported AshTray.f540x", text)
            self.assertIn("AshTray-import.log", text)
            self.assertTrue(os.path.exists(os.path.join(tmp, "AshTray-import.log")))
        self.assertEqual(self.app.documents.created[0].design.rootComponent.sketches.count, 1)
        # The bundle is unpacked to a temporary directory; it must not be left behind.
        self.assertEqual([name for name in after - before if name.startswith("f540x-import-")], [])

    def test_import_one_reports_a_file_that_is_not_a_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "notes.f540x")
            with open(path, "w") as f:
                f.write("not a zip")
            text = addin._import_one(path)
        self.assertIn("notes.f540x failed", text)
        self.assertEqual(self.app.documents.created, [])


if __name__ == "__main__":
    unittest.main()
