from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeDocument:
    def __init__(self, name: str, *, blank: bool):
        self.name = name
        self.blank = blank
        self.next = None

    def GetDocumentName(self):
        return self.name

    def SetDocumentName(self, name):
        self.name = name

    def GetNext(self):
        return self.next

    def IsBlank(self):
        return self.blank


class DocumentIoActivationTest(unittest.TestCase):
    def setUp(self):
        self.user_doc = _FakeDocument("user-scene", blank=False)
        self.documents = [self.user_doc]
        self.active_doc = self.user_doc
        self.insert_calls = 0
        self.active_changes = []

        c4d = types.ModuleType("c4d")
        documents = types.ModuleType("c4d.documents")
        documents.GetActiveDocument = lambda: self.active_doc
        documents.GetFirstDocument = lambda: self.documents[0] if self.documents else None
        documents.BaseDocument = lambda: _FakeDocument("", blank=True)
        documents.LoadDocument = lambda *_args: _FakeDocument("loaded-scene.c4d", blank=False)

        def insert_base_document(doc):
            self.insert_calls += 1
            if self.active_doc in self.documents and self.active_doc.IsBlank():
                self.documents.remove(self.active_doc)
            self.documents.append(doc)
            self._link_documents()
            self.active_doc = doc

        def set_active_document(doc):
            self.active_doc = doc
            self.active_changes.append(doc.name)

        documents.InsertBaseDocument = insert_base_document
        documents.SetActiveDocument = set_active_document
        c4d.documents = documents
        c4d.EventAdd = lambda: None
        c4d.SCENEFILTER_OBJECTS = 1
        c4d.SCENEFILTER_MATERIALS = 2

        bridge = types.ModuleType("bridge")
        bridge.__path__ = []
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = []
        helpers = types.ModuleType("bridge.handlers._helpers")
        helpers._find_object = lambda *_args: None
        helpers._find_take = lambda *_args: None
        helpers._require_abs_path = lambda value, **_kwargs: str(value)
        helpers._require_writable_path = lambda value: str(value)
        helpers._resolve_format = lambda *_args: 0
        helpers._resolve_handle = lambda *_args: None

        self.module_patch = patch.dict(
            sys.modules,
            {
                "c4d": c4d,
                "c4d.documents": documents,
                "bridge": bridge,
                "bridge.handlers": handlers,
                "bridge.handlers._helpers": helpers,
            },
        )
        self.module_patch.start()
        self.document_io = self._load_module(
            "bridge.handlers.document_io",
            REPO_ROOT / "plugin/cinema4d_mcp_bridge/bridge/handlers/document_io.py",
        )

    def tearDown(self):
        self.module_patch.stop()

    def test_new_document_refuses_before_insertion_when_blank_active_would_be_destroyed(self):
        self.user_doc.blank = True

        with self.assertRaisesRegex(RuntimeError, "blank active document"):
            self.document_io.handle_new_document({"name": "isolated", "make_active": False})

        self.assertEqual(self.insert_calls, 0)
        self.assertEqual(self.documents, [self.user_doc])
        self.assertIs(self.active_doc, self.user_doc)

    def test_new_document_restores_nonblank_previous_active_document(self):
        result = self.document_io.handle_new_document({"name": "isolated", "make_active": False})

        self.assertEqual(self.insert_calls, 1)
        self.assertEqual([doc.name for doc in self.documents], ["user-scene", "isolated"])
        self.assertIs(self.active_doc, self.user_doc)
        self.assertEqual(self.active_changes, ["user-scene"])
        self.assertEqual(result["switched"], False)
        self.assertEqual(result["active_document"], "user-scene")

    def test_open_document_refuses_before_insertion_when_blank_active_would_be_destroyed(self):
        self.user_doc.blank = True

        with self.assertRaisesRegex(RuntimeError, "blank active document"):
            self.document_io.handle_open_document({"path": "C:/scene.c4d", "make_active": False})

        self.assertEqual(self.insert_calls, 0)
        self.assertEqual(self.documents, [self.user_doc])
        self.assertIs(self.active_doc, self.user_doc)

    def test_make_active_true_retains_the_inserted_document_as_active(self):
        result = self.document_io.handle_new_document({"name": "active-new", "make_active": True})

        self.assertEqual(self.insert_calls, 1)
        self.assertEqual([doc.name for doc in self.documents], ["user-scene", "active-new"])
        self.assertEqual(self.active_doc.name, "active-new")
        self.assertEqual(result["switched"], True)
        self.assertEqual(result["active_document"], "active-new")

    def _link_documents(self):
        for index, doc in enumerate(self.documents):
            doc.next = self.documents[index + 1] if index + 1 < len(self.documents) else None

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
