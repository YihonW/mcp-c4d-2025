from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeDocument:
    def __init__(self, name: str):
        self.name = name
        self.next = None
        self.writes = []
        self.undo_events = []

    def GetDocumentName(self):
        return self.name

    def GetNext(self):
        return self.next

    def StartUndo(self):
        self.undo_events.append("start")

    def EndUndo(self):
        self.undo_events.append("end")


class BatchDocumentScopeTest(unittest.TestCase):
    def setUp(self):
        self.user_doc = _FakeDocument("user-scene")
        self.temp_doc = _FakeDocument("e2e-temp")
        self.user_doc.next = self.temp_doc
        self.active_doc = self.user_doc
        self.active_changes = []

        c4d = types.ModuleType("c4d")
        documents = types.ModuleType("c4d.documents")
        documents.GetActiveDocument = lambda: self.active_doc
        documents.GetFirstDocument = lambda: self.user_doc

        def set_active_document(doc):
            self.active_doc = doc
            self.active_changes.append(doc.name)

        documents.SetActiveDocument = set_active_document
        c4d.documents = documents
        c4d.EventAdd = lambda: None
        c4d.CallCommand = lambda *_args: None

        bridge = types.ModuleType("bridge")
        bridge.__path__ = []
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = []
        helpers = types.ModuleType("bridge.handlers._helpers")
        for name in (
            "_describe_params",
            "_dump_container",
            "_find_material",
            "_find_object",
            "_find_object_by_path",
            "_find_render_data",
            "_find_tag",
            "_find_take",
            "_find_videopost",
            "_json_safe",
            "_plugin_type_alias",
            "_resolve_handle",
            "_shader_at",
        ):
            setattr(helpers, name, lambda *_args, **_kwargs: None)
        log = types.ModuleType("bridge.log")
        log.log = lambda *_args: None

        self.handlers = handlers
        self.fake_modules = {
            "c4d": c4d,
            "c4d.documents": documents,
            "bridge": bridge,
            "bridge.handlers": handlers,
            "bridge.handlers._helpers": helpers,
            "bridge.log": log,
        }
        self.module_patch = patch.dict(sys.modules, self.fake_modules)
        self.module_patch.start()
        self.script = self._load_module(
            "bridge.handlers.script",
            REPO_ROOT / "plugin/cinema4d_mcp_bridge/bridge/handlers/script.py",
        )

    def tearDown(self):
        self.module_patch.stop()

    def test_document_scoped_batch_writes_only_target_and_restores_active_document(self):
        def write_marker(params):
            active = self.fake_modules["c4d.documents"].GetActiveDocument()
            active.writes.append(params["marker"])
            return {"document": active.name}

        self.handlers.HANDLERS = {"write_marker": write_marker}

        result = self.script.handle_batch(
            {
                "document_name": self.temp_doc.name,
                "ops": [{"op": "write_marker", "args": {"marker": "foundation"}}],
            }
        )

        self.assertEqual(self.user_doc.writes, [])
        self.assertEqual(self.temp_doc.writes, ["foundation"])
        self.assertEqual(result["results"][0]["result"], {"document": self.temp_doc.name})
        self.assertIs(self.active_doc, self.user_doc)
        self.assertEqual(self.active_changes, [self.temp_doc.name, self.user_doc.name])
        self.assertEqual(self.temp_doc.undo_events, ["start", "end"])

    def test_document_scoped_batch_restores_active_document_after_handler_error(self):
        def switch_then_fail(_params):
            self.fake_modules["c4d.documents"].SetActiveDocument(self.temp_doc)
            raise RuntimeError("action failed")

        self.handlers.HANDLERS = {"fail": switch_then_fail}

        result = self.script.handle_batch(
            {
                "document_name": self.temp_doc.name,
                "ops": [{"op": "fail"}],
                "stop_on_error": True,
            }
        )

        self.assertIn("action failed", result["results"][0]["error"])
        self.assertIs(self.active_doc, self.user_doc)

    def test_undo_group_false_skips_only_the_outer_batch_undo_group(self):
        self.handlers.HANDLERS = {"active": lambda _params: {"document": self.active_doc.name}}

        result = self.script.handle_batch(
            {
                "document_name": self.temp_doc.name,
                "undo_group": False,
                "ops": [{"op": "active"}],
            }
        )

        self.assertEqual(result["results"][0]["result"], {"document": self.temp_doc.name})
        self.assertEqual(self.temp_doc.undo_events, [])
        self.assertIs(self.active_doc, self.user_doc)

    def test_unscoped_batch_keeps_the_default_outer_undo_group(self):
        self.handlers.HANDLERS = {"active": lambda _params: {"document": self.active_doc.name}}

        result = self.script.handle_batch({"ops": [{"op": "active"}]})

        self.assertEqual(result["results"][0]["result"], {"document": self.user_doc.name})
        self.assertEqual(self.user_doc.undo_events, ["start", "end"])
        self.assertIs(self.active_doc, self.user_doc)

    def test_document_scope_rejects_a_non_unique_document_name_without_switching_focus(self):
        duplicate = _FakeDocument(self.temp_doc.name)
        self.temp_doc.next = duplicate
        self.handlers.HANDLERS = {"active": lambda _params: {"document": self.active_doc.name}}

        with self.assertRaisesRegex(ValueError, "document_name must be unique"):
            self.script.handle_batch(
                {
                    "document_name": self.temp_doc.name,
                    "ops": [{"op": "active"}],
                }
            )

        self.assertIs(self.active_doc, self.user_doc)
        self.assertEqual(self.active_changes, [])

    @staticmethod
    def _load_module(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
