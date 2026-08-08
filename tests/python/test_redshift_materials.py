from __future__ import annotations

import contextlib
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from redshift_fakes import make_c4d_runtime, make_maxon_runtime, make_redshift_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin" / "cinema4d_mcp_bridge"
RS_NODE_SPACE_ID = "com.redshift3d.redshift4c4d.class.nodespace"
MATERIAL_ASSETS = (
    "com.redshift3d.redshift4c4d.node.output",
    "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
)


class FakeMaterial:
    def __init__(self, name: str):
        self.name = name
        self.next: FakeMaterial | None = None

    def GetName(self):
        return self.name

    def GetNext(self):
        return self.next


class FakeMaterialDocument:
    def __init__(self, document, materials=()):
        self.document = document
        self.materials = list(materials)
        self.undo_calls = []
        self.undo_events = []
        self._link_materials()

    def _link_materials(self):
        for current, following in zip(self.materials, self.materials[1:], strict=False):
            current.next = following
        if self.materials:
            self.materials[-1].next = None

    def GetFirstMaterial(self):
        return self.materials[0] if self.materials else None

    def AddUndo(self, undo_type, material):
        self.undo_calls.append((undo_type, material))
        self.undo_events.append(("add", undo_type, material))

    def StartUndo(self):
        self.undo_events.append("start")

    def EndUndo(self):
        self.undo_events.append("end")

    def add_material(self, material):
        self.materials.append(material)
        self._link_materials()


class FakeGraphDescription:
    def __init__(self, document_state, document_map):
        self.document_state = document_state
        self.document_map = document_map
        self.calls = []
        self.active_document = None

    def CreateGraph(self, material_or_name, *, nodeSpaceId, createEmpty):
        self.active_document = self.document_state.active
        self.calls.append((material_or_name, str(nodeSpaceId), createEmpty))
        if isinstance(material_or_name, str):
            self.document_map[self.document_state.active].add_material(
                FakeMaterial(material_or_name)
            )
        return object()


class RedshiftMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.c4d, self.documents, self.document_state, _ = make_c4d_runtime(
            document_names=["main", "user"]
        )
        self.c4d.UNDOTYPE_NEW = 100
        self.maxon, _ = make_maxon_runtime(MATERIAL_ASSETS)
        self.redshift = make_redshift_runtime()
        self.document_map = {
            document: FakeMaterialDocument(document) for document in self.document_state.items
        }
        for document, material_document in self.document_map.items():
            document.GetFirstMaterial = material_document.GetFirstMaterial
            document.AddUndo = material_document.AddUndo
            document.StartUndo = material_document.StartUndo
            document.EndUndo = material_document.EndUndo
        self.user_document = self.document_state.items[1]
        self.graph_description = FakeGraphDescription(self.document_state, self.document_map)
        self.maxon.GraphDescription = self.graph_description
        self.maxon.NodeSpaceIdentifiers = types.SimpleNamespace(RedshiftMaterial=RS_NODE_SPACE_ID)
        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        parent_helpers = types.ModuleType("bridge.handlers._helpers")
        parent_helpers._require_abs_path = lambda value, **_kwargs: str(value)
        parent_helpers._require_writable_path = lambda value: str(value)
        self.modules = {
            "c4d": self.c4d,
            "c4d.documents": self.documents,
            "maxon": self.maxon,
            "redshift": self.redshift,
            "bridge": bridge,
            "bridge.handlers": handlers,
            "bridge.handlers._helpers": parent_helpers,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        sys.path.insert(0, str(PLUGIN_ROOT))

    def tearDown(self):
        for name in tuple(sys.modules):
            if name.startswith("bridge.handlers.redshift"):
                sys.modules.pop(name, None)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(PLUGIN_ROOT))
        self.module_patch.stop()

    @property
    def active_document(self):
        return self.document_state.active

    @property
    def graph_create_calls(self):
        return len(self.graph_description.calls)

    def handle_rs_create_material(self, params):
        return importlib.import_module(
            "bridge.handlers.redshift.materials"
        ).handle_rs_create_material(params)

    def test_creates_a_material_in_the_requested_document_and_records_undo(self):
        result = self.handle_rs_create_material({"document_name": "user", "name": "RS_Mat"})

        self.assertEqual(result["handle"], {"kind": "material", "name": "RS_Mat"})
        self.assertEqual(result["node_space_id"], RS_NODE_SPACE_ID)
        self.assertTrue(result["created"])
        self.assertTrue(result["undo_supported"])
        self.assertIs(self.graph_description.active_document, self.user_document)
        self.assertIs(self.active_document, self.document_state.items[0])
        self.assertEqual(
            self.graph_description.calls,
            [("RS_Mat", RS_NODE_SPACE_ID, False)],
        )
        self.assertEqual(
            self.document_map[self.user_document].undo_calls,
            [(self.c4d.UNDOTYPE_NEW, self.document_map[self.user_document].materials[0])],
        )
        self.assertEqual(
            self.document_map[self.user_document].undo_events,
            [
                "start",
                (
                    "add",
                    self.c4d.UNDOTYPE_NEW,
                    self.document_map[self.user_document].materials[0],
                ),
                "end",
            ],
        )

    def test_marks_undo_unsupported_without_a_complete_or_startable_undo_surface(self):
        del self.user_document.EndUndo

        incomplete = self.handle_rs_create_material({"document_name": "user", "name": "NoEnd"})

        self.assertFalse(incomplete["undo_supported"])
        self.assertEqual(self.document_map[self.user_document].undo_calls, [])
        self.assertEqual(self.document_map[self.user_document].undo_events, [])

        self.user_document.EndUndo = self.document_map[self.user_document].EndUndo

        def fail_start_undo():
            self.document_map[self.user_document].undo_events.append("start")
            raise RuntimeError("undo unavailable")

        self.user_document.StartUndo = fail_start_undo
        failed_start = self.handle_rs_create_material(
            {"document_name": "user", "name": "StartFails"}
        )

        self.assertFalse(failed_start["undo_supported"])
        self.assertEqual(self.document_map[self.user_document].undo_calls, [])
        self.assertEqual(self.document_map[self.user_document].undo_events, ["start"])

        self.document_map[self.user_document].undo_calls.clear()
        self.document_map[self.user_document].undo_events.clear()
        self.user_document.StartUndo = lambda: False
        false_start = self.handle_rs_create_material(
            {"document_name": "user", "name": "StartReturnsFalse"}
        )

        self.assertFalse(false_start["undo_supported"])
        self.assertEqual(self.document_map[self.user_document].undo_calls, [])
        self.assertEqual(self.document_map[self.user_document].undo_events, [])

    def test_reuses_exactly_one_same_name_material_when_requested(self):
        material = FakeMaterial("RS_Mat")
        self.document_map[self.user_document].add_material(material)

        result = self.handle_rs_create_material(
            {"document_name": "user", "name": "RS_Mat", "update_if_exists": True}
        )

        self.assertFalse(result["created"])
        self.assertEqual(self.graph_description.calls, [(material, RS_NODE_SPACE_ID, False)])
        self.assertEqual(self.document_map[self.user_document].materials, [material])

    def test_rejects_default_duplicate_and_ambiguous_update_before_graph_creation(self):
        self.document_map[self.user_document].add_material(FakeMaterial("RS_Mat"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.handle_rs_create_material({"document_name": "user", "name": "RS_Mat"})
        self.assertEqual(self.graph_create_calls, 0)

        self.document_map[self.user_document].add_material(FakeMaterial("Dup"))
        self.document_map[self.user_document].add_material(FakeMaterial("Dup"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.handle_rs_create_material(
                {"document_name": "user", "name": "Dup", "update_if_exists": True}
            )
        self.assertEqual(self.graph_create_calls, 0)

    def test_rejects_missing_material_capability_before_any_write(self):
        self.maxon.AssetInterface.GetUserPrefsRepository().assets.pop()

        with self.assertRaisesRegex(RuntimeError, "Redshift capability unavailable"):
            self.handle_rs_create_material({"document_name": "user", "name": "RS_Mat"})

        self.assertEqual(self.graph_create_calls, 0)
        self.assertEqual(self.document_map[self.user_document].materials, [])


if __name__ == "__main__":
    unittest.main()
