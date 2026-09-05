from __future__ import annotations

import contextlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from redshift_fakes import make_c4d_runtime, make_redshift_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin" / "cinema4d_mcp_bridge"


class FakeDescLevel:
    def __init__(self, identifier, dtype, creator):
        self.identifier = identifier
        self.id = identifier
        self.dtype = dtype
        self.creator = creator


class FakeDescID:
    def __init__(self, *levels):
        self.levels = levels

    def __getitem__(self, index):
        return self.levels[index]

    def GetDepth(self):
        return len(self.levels)


class FakeObject:
    def __init__(self, type_id):
        self.type_id = type_id
        self.name = ""
        self.next = None
        self.up = None
        self.params = {}
        self.set_calls = []
        self.position = None
        self.rotation = None
        self.raise_on_set = False

    def GetType(self):
        return self.type_id

    def GetName(self):
        return self.name

    def SetName(self, name):
        self.name = name

    def GetNext(self):
        return self.next

    def GetDown(self):
        return None

    def GetUp(self):
        return self.up

    def SetRelPos(self, value):
        self.position = value

    def SetRelRot(self, value):
        self.rotation = value

    def __setitem__(self, key, value):
        if self.raise_on_set:
            raise RuntimeError("injected parameter failure")
        self.set_calls.append((key, value))
        self.params[key] = value

    def __getitem__(self, key):
        return self.params[key]

    def GetDescription(self, _flags):
        return [({}, FakeDescID(FakeDescLevel(304, 1036765, self.type_id)), None)]


class FakeObjectDocument:
    def __init__(self, document):
        self.document = document
        self.objects = []
        self.inserted_objects = []
        self.undo_events = []
        self.add_undo_returns_false = False

    def _link(self):
        for current, following in zip(self.objects, self.objects[1:], strict=False):
            current.next = following
        if self.objects:
            self.objects[-1].next = None

    def GetFirstObject(self):
        return self.objects[0] if self.objects else None

    def InsertObject(self, obj):
        self.objects.append(obj)
        self.inserted_objects.append(obj)
        self.undo_events.append(("insert", obj))
        self._link()

    def StartUndo(self):
        self.undo_events.append("start")

    def AddUndo(self, undo_type, obj):
        self.undo_events.append(("add", undo_type, obj))
        if self.add_undo_returns_false:
            return False

    def EndUndo(self):
        self.undo_events.append("end")


class RedshiftLightsCameraTest(unittest.TestCase):
    def setUp(self):
        self.c4d, self.documents, self.document_state, _ = make_c4d_runtime(
            document_names=["main", "target"]
        )
        self.c4d.Orslight = 7001
        self.c4d.Orscamera = 7002
        self.c4d.Olight = 7003
        self.c4d.UNDOTYPE_NEW = 100
        self.c4d.UNDOTYPE_CHANGE = 101
        self.c4d.DTYPE_STRING = 202
        self.c4d.DESCFLAGS_DESC_0 = 0
        self.c4d.REDSHIFT_LIGHT_TYPE = 300
        self.c4d.REDSHIFT_LIGHT_PHYSICAL_COLOR = 301
        self.c4d.REDSHIFT_LIGHT_PHYSICAL_INTENSITY = 302
        self.c4d.REDSHIFT_LIGHT_PHYSICAL_EXPOSURE = 303
        self.c4d.REDSHIFT_LIGHT_DOME_COLOR = 311
        self.c4d.REDSHIFT_LIGHT_DOME_MULTIPLIER = 312
        self.c4d.REDSHIFT_LIGHT_DOME_EXPOSURE0 = 313
        self.c4d.REDSHIFT_LIGHT_PHYSICALSUN_TINT = 321
        self.c4d.REDSHIFT_LIGHT_PHYSICALSUN_MULTIPLIER = 322
        self.c4d.REDSHIFT_LIGHT_DOME_TEX0 = 304
        self.c4d.REDSHIFT_FILE_PATH = 305
        self.c4d.RSCAMERAOBJECT_EXPOSURE = 401
        self.c4d.RSCAMERAOBJECT_SHUTTER_TIME_RATIO = 402
        self.c4d.RSCAMERAOBJECT_SHUTTER_ANGLE = 403
        self.c4d.RSCAMERAOBJECT_FOCUS_DISTANCE = 404
        self.c4d.RSCAMERAOBJECT_FNUMBER_VALUE = 405
        self.c4d.RSCAMERAOBJECT_BOKEH_ENABLED = 406
        self.c4d.DescLevel = FakeDescLevel
        self.c4d.DescID = FakeDescID
        self.c4d.Vector = lambda x, y, z: (x, y, z)
        self.c4d.BaseObject = FakeObject
        self.document_map = {
            document: FakeObjectDocument(document) for document in self.document_state.items
        }
        for document, object_document in self.document_map.items():
            document.GetFirstObject = object_document.GetFirstObject
            document.InsertObject = object_document.InsertObject
            document.StartUndo = object_document.StartUndo
            document.AddUndo = object_document.AddUndo
            document.EndUndo = object_document.EndUndo
        self.main_document = self.document_state.items[0]
        self.target_document = self.document_state.items[1]

        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        parent_helpers = types.ModuleType("bridge.handlers._helpers")

        def require_abs_path(value, **_kwargs):
            if value == "C:/missing/dome.exr":
                raise ValueError(f"file not found: {value}")
            return str(value)

        parent_helpers._require_abs_path = require_abs_path
        parent_helpers._require_writable_path = lambda value: str(value)
        parent_helpers._object_path = lambda obj: f"/{obj.GetName()}"
        self.modules = {
            "c4d": self.c4d,
            "c4d.documents": self.documents,
            "maxon": types.ModuleType("maxon"),
            "redshift": make_redshift_runtime(),
            "bridge": bridge,
            "bridge.handlers": handlers,
            "bridge.handlers._helpers": parent_helpers,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        sys.path.insert(0, str(PLUGIN_ROOT))

        from bridge.handlers.redshift.camera import handle_rs_set_camera
        from bridge.handlers.redshift.lights import handle_rs_create_light

        self.handle_rs_create_light = handle_rs_create_light
        self.handle_rs_set_camera = handle_rs_set_camera

    def tearDown(self):
        for name in tuple(sys.modules):
            if name.startswith("bridge.handlers.redshift"):
                sys.modules.pop(name, None)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(PLUGIN_ROOT))
        self.module_patch.stop()

    @property
    def target(self):
        return self.document_map[self.target_document]

    def add_object(self, name, type_id, document=None):
        obj = FakeObject(type_id)
        obj.SetName(name)
        target = self.document_map[document or self.target_document]
        target.objects.append(obj)
        target._link()
        return obj

    def test_creates_every_runtime_light_type_with_exact_type_and_undo(self):
        expected_types = {
            "area": self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA,
            "dome": self.c4d.REDSHIFT_LIGHT_TYPE_DOME,
            "sun": self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICALSUN,
            "point": self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_POINT,
            "spot": self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_SPOT,
        }

        for light_type, expected in expected_types.items():
            with self.subTest(light_type=light_type):
                self.target.objects.clear()
                self.target.inserted_objects.clear()
                self.target.undo_events.clear()
                result = self.handle_rs_create_light(
                    {"document_name": "target", "name": f"RS_{light_type}", "type": light_type}
                )
                light = self.target.objects[0]
                self.assertEqual(light.GetType(), self.c4d.Orslight)
                self.assertEqual(light.params[self.c4d.REDSHIFT_LIGHT_TYPE], expected)
                self.assertEqual(
                    result["handle"],
                    {"kind": "object", "path": f"/RS_{light_type}", "name": f"RS_{light_type}"},
                )
                self.assertTrue(result["created"])
                self.assertTrue(result["undo_supported"])
                self.assertEqual(
                    self.target.undo_events,
                    [
                        "start",
                        ("insert", light),
                        ("add", self.c4d.UNDOTYPE_NEW, light),
                        "end",
                    ],
                )

    def test_rejects_an_unavailable_requested_light_type_before_insertion(self):
        delattr(self.c4d, "REDSHIFT_LIGHT_TYPE_PHYSICALSUN")

        with self.assertRaisesRegex(RuntimeError, "sun.*unsupported"):
            self.handle_rs_create_light({"name": "RS_Sun", "type": "sun"})

        self.assertEqual(self.document_map[self.main_document].inserted_objects, [])

    def test_rejects_missing_requested_light_property_before_insertion_and_restores_document(self):
        delattr(self.c4d, "REDSHIFT_LIGHT_PHYSICAL_EXPOSURE")

        with self.assertRaisesRegex(RuntimeError, "exposure.*unsupported"):
            self.handle_rs_create_light(
                {"document_name": "target", "name": "RS_Area", "type": "area", "exposure": 1}
            )

        self.assertEqual(self.target.inserted_objects, [])
        self.assertIs(self.document_state.active, self.main_document)

    def test_rejects_missing_light_type_property_and_non_positive_intensity_before_insertion(
        self,
    ):
        delattr(self.c4d, "REDSHIFT_LIGHT_TYPE")
        with self.assertRaisesRegex(RuntimeError, "type.*unsupported"):
            self.handle_rs_create_light({"name": "RS_Area", "type": "area"})
        self.assertEqual(self.document_map[self.main_document].inserted_objects, [])

        self.c4d.REDSHIFT_LIGHT_TYPE = 300
        with self.assertRaisesRegex(ValueError, "intensity.*positive"):
            self.handle_rs_create_light({"name": "RS_Area", "type": "area", "intensity": 0})
        self.assertEqual(self.document_map[self.main_document].inserted_objects, [])

    def test_applies_light_transform_and_dome_texture_with_runtime_descid(self):
        result = self.handle_rs_create_light(
            {
                "document_name": "target",
                "name": "RS_Dome",
                "type": "dome",
                "position": [1, 2, 3],
                "rotation": [0.1, 0.2, 0.3],
                "color": [0.1, 0.2, 0.3],
                "intensity": 2,
                "exposure": -1,
                "dome_texture": "C:/textures/dome.exr",
            }
        )

        light = self.target.objects[0]
        self.assertEqual(light.position, (1.0, 2.0, 3.0))
        self.assertEqual(light.rotation, (0.1, 0.2, 0.3))
        self.assertEqual(light.params[self.c4d.REDSHIFT_LIGHT_DOME_COLOR], (0.1, 0.2, 0.3))
        self.assertEqual(light.params[self.c4d.REDSHIFT_LIGHT_DOME_MULTIPLIER], 2.0)
        self.assertEqual(light.params[self.c4d.REDSHIFT_LIGHT_DOME_EXPOSURE0], -1.0)
        texture_descid = next(key for key in light.params if isinstance(key, FakeDescID))
        self.assertEqual(
            [(level.identifier, level.dtype, level.creator) for level in texture_descid.levels],
            [
                (
                    self.c4d.REDSHIFT_LIGHT_DOME_TEX0,
                    1036765,
                    self.c4d.Orslight,
                ),
                (self.c4d.REDSHIFT_FILE_PATH, self.c4d.DTYPE_STRING, 0),
            ],
        )
        self.assertEqual(light.params[texture_descid], "C:/textures/dome.exr")
        self.assertEqual(
            result["applied"],
            ["position", "rotation", "color", "intensity", "exposure", "dome_texture"],
        )

    def test_rejects_invalid_dome_texture_before_insertion(self):
        with self.assertRaisesRegex(ValueError, "file not found"):
            self.handle_rs_create_light(
                {"name": "RS_Dome", "type": "dome", "dome_texture": "C:/missing/dome.exr"}
            )
        self.assertEqual(self.document_map[self.main_document].inserted_objects, [])

    def test_missing_dome_description_rejects_before_insertion(self):
        with (
            patch.object(FakeObject, "GetDescription", return_value=[]),
            self.assertRaisesRegex(RuntimeError, "runtime texture description unavailable"),
        ):
            self.handle_rs_create_light(
                {
                    "document_name": "target",
                    "name": "RS_Dome",
                    "type": "dome",
                    "dome_texture": "C:/textures/dome.exr",
                }
            )
        self.assertEqual(self.target.inserted_objects, [])
        self.assertEqual(self.target.undo_events, [])
        self.assertIs(self.document_state.active, self.main_document)

    def test_sun_uses_its_parameters_and_rejects_unavailable_exposure(self):
        result = self.handle_rs_create_light(
            {"document_name": "target", "name": "Sun", "type": "sun", "intensity": 3}
        )
        self.assertEqual(result["applied"], ["intensity"])
        self.assertEqual(
            self.target.objects[0].params[self.c4d.REDSHIFT_LIGHT_PHYSICALSUN_MULTIPLIER], 3
        )
        with self.assertRaisesRegex(RuntimeError, "exposure unsupported"):
            self.handle_rs_create_light(
                {"document_name": "target", "name": "InvalidSun", "type": "sun", "exposure": 1}
            )
        self.assertEqual(len(self.target.inserted_objects), 1)

    def test_light_updates_only_an_exact_redshift_object_and_rejects_duplicates(self):
        wrong_type = self.add_object("RS_Area", self.c4d.Olight)
        with self.assertRaisesRegex(ValueError, "not a Redshift light"):
            self.handle_rs_create_light(
                {
                    "document_name": "target",
                    "name": "RS_Area",
                    "type": "area",
                    "update_if_exists": True,
                }
            )
        self.assertEqual(wrong_type.GetType(), self.c4d.Olight)
        self.assertEqual(self.target.inserted_objects, [])

        light = self.add_object("RS_Update", self.c4d.Orslight)
        light.params[self.c4d.REDSHIFT_LIGHT_TYPE] = self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA
        with self.assertRaisesRegex(ValueError, "type.*does not match"):
            self.handle_rs_create_light(
                {
                    "document_name": "target",
                    "name": "RS_Update",
                    "type": "spot",
                    "update_if_exists": True,
                    "intensity": 3,
                }
            )
        self.assertEqual(light.GetType(), self.c4d.Orslight)
        self.assertEqual(light.set_calls, [])
        self.assertEqual(self.target.undo_events, [])

        result = self.handle_rs_create_light(
            {
                "document_name": "target",
                "name": "RS_Update",
                "type": "area",
                "update_if_exists": True,
                "intensity": 3,
            }
        )
        self.assertFalse(result["created"])
        self.assertIs(light, self.target.objects[-1])
        self.assertEqual(light.GetType(), self.c4d.Orslight)
        self.assertEqual(
            light.params[self.c4d.REDSHIFT_LIGHT_TYPE], self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA
        )
        self.assertEqual(light.set_calls, [(self.c4d.REDSHIFT_LIGHT_PHYSICAL_INTENSITY, 3.0)])
        self.assertEqual(
            self.target.undo_events[-3:], ["start", ("add", self.c4d.UNDOTYPE_CHANGE, light), "end"]
        )

        self.add_object("Duplicate", self.c4d.Orslight)
        self.add_object("Duplicate", self.c4d.Orslight)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.handle_rs_create_light(
                {
                    "document_name": "target",
                    "name": "Duplicate",
                    "type": "area",
                    "update_if_exists": True,
                }
            )

    def test_add_undo_false_closes_the_group_and_marks_light_and_camera_unsupported(self):
        self.target.add_undo_returns_false = True

        light_result = self.handle_rs_create_light(
            {"document_name": "target", "name": "RS_Area", "type": "area"}
        )
        light = self.target.objects[0]
        self.assertFalse(light_result["undo_supported"])
        self.assertEqual(
            self.target.undo_events,
            [
                "start",
                ("insert", light),
                ("add", self.c4d.UNDOTYPE_NEW, light),
                "end",
            ],
        )

        self.target.undo_events.clear()
        camera_result = self.handle_rs_set_camera({"document_name": "target", "name": "RS_Camera"})
        camera = self.target.objects[-1]
        self.assertFalse(camera_result["undo_supported"])
        self.assertEqual(
            self.target.undo_events,
            [
                "start",
                ("insert", camera),
                ("add", self.c4d.UNDOTYPE_NEW, camera),
                "end",
            ],
        )

        self.target.undo_events.clear()
        self.target_document.StartUndo = lambda: False
        no_start_result = self.handle_rs_create_light(
            {"document_name": "target", "name": "RS_NoUndo", "type": "area"}
        )
        self.assertFalse(no_start_result["undo_supported"])
        self.assertEqual(self.target.undo_events, [("insert", self.target.objects[-1])])

    def test_light_ends_undo_after_write_error(self):
        light = self.add_object("RS_Error", self.c4d.Orslight)
        light.params[self.c4d.REDSHIFT_LIGHT_TYPE] = self.c4d.REDSHIFT_LIGHT_TYPE_PHYSICAL_AREA
        light.raise_on_set = True

        with self.assertRaisesRegex(RuntimeError, "injected parameter failure"):
            self.handle_rs_create_light(
                {
                    "document_name": "target",
                    "name": "RS_Error",
                    "type": "area",
                    "update_if_exists": True,
                    "intensity": 3,
                }
            )

        self.assertEqual(
            self.target.undo_events[-3:], ["start", ("add", self.c4d.UNDOTYPE_CHANGE, light), "end"]
        )
        self.assertIs(self.document_state.active, self.main_document)

    def test_camera_creates_updates_and_preserves_exact_redshift_type(self):
        result = self.handle_rs_set_camera(
            {
                "document_name": "target",
                "name": "RS_Camera",
                "position": [5, 6, 7],
                "rotation": [0.4, 0.5, 0.6],
                "exposure": 1,
                "shutter_time": 0.25,
                "shutter_angle": 180,
                "focus_distance": 50,
                "f_stop": 2.8,
                "depth_of_field": True,
            }
        )
        camera = self.target.objects[0]
        self.assertEqual(camera.GetType(), self.c4d.Orscamera)
        self.assertEqual(camera.position, (5.0, 6.0, 7.0))
        self.assertEqual(camera.rotation, (0.4, 0.5, 0.6))
        self.assertEqual(
            result["applied"],
            [
                "position",
                "rotation",
                "exposure",
                "shutter_time",
                "shutter_angle",
                "focus_distance",
                "f_stop",
                "depth_of_field",
            ],
        )
        self.assertEqual(result["unavailable"], [])

        updated = self.handle_rs_set_camera(
            {
                "document_name": "target",
                "name": "RS_Camera",
                "update_if_exists": True,
                "exposure": 2,
            }
        )
        self.assertFalse(updated["created"])
        self.assertIs(self.target.objects[0], camera)
        self.assertEqual(camera.GetType(), self.c4d.Orscamera)

    def test_camera_reports_missing_requested_parameter_and_applies_other_available_parameters(
        self,
    ):
        delattr(self.c4d, "RSCAMERAOBJECT_SHUTTER_ANGLE")

        result = self.handle_rs_set_camera(
            {"document_name": "target", "name": "RS_Camera", "exposure": 1, "shutter_angle": 180}
        )

        camera = self.target.objects[0]
        self.assertEqual(camera.params[self.c4d.RSCAMERAOBJECT_EXPOSURE], 1.0)
        self.assertEqual(result["applied"], ["exposure"])
        self.assertEqual(
            result["unavailable"],
            [
                {
                    "setting": "shutter_angle",
                    "reason": "Cinema 4D symbol unavailable: RSCAMERAOBJECT_SHUTTER_ANGLE",
                }
            ],
        )

    def test_camera_rejects_wrong_type_duplicates_and_invalid_values(self):
        self.add_object("Camera", self.c4d.Olight)
        with self.assertRaisesRegex(ValueError, "not a Redshift camera"):
            self.handle_rs_set_camera(
                {"document_name": "target", "name": "Camera", "update_if_exists": True}
            )
        self.add_object("DuplicateCamera", self.c4d.Orscamera)
        self.add_object("DuplicateCamera", self.c4d.Orscamera)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.handle_rs_set_camera(
                {"document_name": "target", "name": "DuplicateCamera", "update_if_exists": True}
            )
        with self.assertRaisesRegex(ValueError, "shutter_time.*positive"):
            self.handle_rs_set_camera({"name": "Invalid", "shutter_time": 0})
        with self.assertRaisesRegex(ValueError, "position.*three"):
            self.handle_rs_set_camera({"name": "Invalid", "position": [1, 2]})


if __name__ == "__main__":
    unittest.main()
