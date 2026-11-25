"""Runs the f540x exporter against mock Fusion API objects (no Fusion needed).

    python -m unittest discover -s tools/fusion-bridge/tests

Only checks that the exporter's code paths run and produce the schema's shape; whether
the real Fusion API behaves like these mocks is checked by running the add-in in Fusion.
"""

import json
import os
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "Fission540Bridge"))
sys.path.insert(0, HERE)

import fusion_mock  # noqa: E402

fusion_mock.install()
make_design = fusion_mock.make_design

from f540x import exporter  # noqa: E402


class ExporterTest(unittest.TestCase):
    def test_describe_design(self):
        design = make_design()
        e = exporter.Exporter(types.SimpleNamespace(version="2.0.test", activeDocument=None), design)
        data = e.describe_design({"c0": "step/c0.step"})
        json.dumps(data)  # must be serialisable

        self.assertEqual(data["schema"], "f540x/0")
        self.assertEqual(data["designType"], "parametric")
        self.assertEqual(data["rootComponent"], "c0")
        self.assertEqual(data["components"][0]["bodies"][0]["volume"], 8.0)
        self.assertEqual(data["userParameters"][0]["name"], "width")

        sketch = data["sketches"][0]
        self.assertEqual(sketch["plane"], {"kind": "constructionPlane", "name": "XY", "component": "c0"})
        self.assertEqual([p["id"] for p in sketch["points"]], ["s0.0", "s0.1"])
        line, circle = sketch["curves"]
        self.assertEqual((line["type"], line["start"], line["end"]), ("SketchLine", "s0.0", "s0.1"))
        self.assertEqual((circle["center"], circle["radius"]), ("s0.0", 1.0))
        self.assertEqual(sketch["constraints"][0]["entities"], {"line": line["id"]})
        self.assertEqual(sketch["dimensions"][0]["parameter"], "d1")
        self.assertEqual(sketch["profiles"][0]["loops"][0]["curves"], [circle["id"]])

        items = data["timeline"]["items"]
        self.assertEqual(items[0]["entity"], {"kind": "sketch", "sketch": "s0"})
        extrude = items[1]["entity"]
        self.assertEqual(extrude["type"], "ExtrudeFeature")
        self.assertEqual(extrude["operation"], "NewBodyFeatureOperation")
        self.assertEqual(extrude["extentOne"], {"type": "DistanceExtentDefinition", "distance": "d2"})
        self.assertEqual(extrude["profile"]["loops"][0]["curves"], [circle["id"]])
        self.assertEqual(extrude["parameters"], ["d2"])
        self.assertNotIn("unsupported", extrude)
        self.assertEqual(e.summary.warnings, [])

    def test_bundle(self):
        design = make_design()
        app = types.SimpleNamespace(version="2.0.test", activeDocument=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out", "AshTray.f540x")
            summary = exporter.export_design(app, design, path)
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                data = json.loads(z.read("design.json"))
        self.assertEqual(names, {"design.json", "export.log", "source.f3d",
                                 "step/assembly.step", "step/c0.step"})
        self.assertEqual(data["components"][0]["bodies"][0]["step"], "step/c0.step")
        self.assertEqual(summary.warnings, [])


if __name__ == "__main__":
    unittest.main()
