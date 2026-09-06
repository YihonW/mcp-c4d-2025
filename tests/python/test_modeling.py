from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HANDLERS_ROOT = Path(__file__).resolve().parents[2] / "plugin/cinema4d_mcp_bridge/bridge/handlers"


class FakeObject:
    def __init__(self, name):
        self.name = name
        self.alive = True
        self.doc = None
        self.parent = None
        self.children = []
        self.removals = 0

    def check(self):
        if not self.alive:
            raise ReferenceError("object is not alive")

    def IsAlive(self):
        return self.alive

    def GetName(self):
        self.check()
        return self.name

    def GetDocument(self):
        self.check()
        return self.doc

    def GetUp(self):
        self.check()
        return self.parent

    def GetPred(self):
        self.check()
        if self.doc is None:
            return None
        siblings = self.parent.children if self.parent else self.doc.roots
        index = siblings.index(self)
        return siblings[index - 1] if index else None

    def InsertUnder(self, parent):
        parent.doc.InsertObject(self, parent=parent)

    def Remove(self):
        self.check()
        self.removals += 1
        if self.doc is not None:
            siblings = self.parent.children if self.parent else self.doc.roots
            siblings.remove(self)
        self.parent = self.doc = None


class FakeDocument:
    def __init__(self):
        self.roots = []
        self.StartUndo = Mock()
        self.EndUndo = Mock()
        self.AddUndo = Mock()

    def InsertObject(self, obj, parent=None, pred=None):
        if pred is not None:
            pred.check()
            assert pred.doc is self
            parent = pred.parent
        if parent is not None:
            parent.check()
            assert parent.doc is self
        assert obj.doc is None, "do not insert an already attached object"
        siblings = parent.children if parent else self.roots
        siblings.insert(siblings.index(pred) + 1 if pred else 0, obj)
        obj.parent, obj.doc = parent, self


def object_path(obj):
    return (object_path(obj.GetUp()) + "/" if obj.GetUp() else "") + obj.GetName()


class ModelingTests(unittest.TestCase):
    def setUp(self):
        self.doc = FakeDocument()
        self.c4d = types.ModuleType("c4d")
        self.c4d.BaseObject = FakeObject
        self.c4d.BaseContainer = dict
        self.c4d.MODELINGCOMMANDMODE_ALL = 0
        self.c4d.MCOMMAND_MAKEEDITABLE = 1
        self.c4d.MCOMMAND_TRIANGULATE = 2
        self.c4d.UNDOTYPE_NEW = 10
        self.c4d.UNDOTYPE_DELETE = 11
        self.c4d.EventAdd = Mock()
        self.c4d.documents = types.SimpleNamespace(GetActiveDocument=lambda: self.doc)
        self.send = Mock()
        self.c4d.utils = types.SimpleNamespace(SendModelingCommand=self.send)
        package = types.ModuleType("modeling_under_test")
        package.__path__ = [str(HANDLERS_ROOT)]
        helpers = types.ModuleType("modeling_under_test._helpers")
        helpers._apply_params = lambda obj, params: obj.update(params)
        helpers._resolve_handle = lambda handle: handle
        helpers._object_path = object_path
        helpers._summary = lambda obj: {"name": obj.GetName()}
        helpers._find_objects_by_name = lambda name: []
        self.module_patch = patch.dict(
            sys.modules,
            {"c4d": self.c4d, package.__name__: package, helpers.__name__: helpers},
        )
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        spec = importlib.util.spec_from_file_location(
            "modeling_under_test.modeling", HANDLERS_ROOT / "modeling.py"
        )
        self.handler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.handler)
        self.parent = FakeObject("joint")
        self.pred = FakeObject("other")
        self.src = FakeObject("arm")
        self.doc.InsertObject(self.parent)
        self.doc.InsertObject(self.pred, parent=self.parent)
        self.doc.InsertObject(self.src, pred=self.pred)

    def run_command(self, command="make_editable"):
        return self.handler.handle_modeling_command({"command": command, "targets": [self.src]})

    def test_deleted_source_keeps_parent_and_predecessor(self):
        replacement = FakeObject("arm")

        def convert(**kwargs):
            self.src.Remove()
            self.src.alive = False
            return [replacement]

        self.send.side_effect = convert
        result = self.run_command()
        self.assertEqual(self.parent.children, [self.pred, replacement])
        self.assertEqual(result["results"][0]["handle"]["path"], "joint/arm")
        self.assertEqual(self.src.removals, 1)
        self.doc.EndUndo.assert_called_once()

    def test_detached_source_keeps_parent_and_predecessor(self):
        replacement = FakeObject("arm")
        self.send.side_effect = lambda **kwargs: (self.src.Remove(), [replacement])[1]
        self.run_command()
        self.assertEqual(self.parent.children, [self.pred, replacement])
        self.assertEqual(self.src.removals, 1)

    def test_attached_source_replaced_in_original_sibling_slot(self):
        replacement = FakeObject("arm")
        self.send.return_value = [replacement]
        self.run_command()
        self.assertEqual(self.parent.children, [self.pred, replacement])
        self.assertEqual(self.src.removals, 1)

    def test_same_object_returned_in_scene_is_not_removed(self):
        self.send.return_value = [self.src]
        result = self.run_command()
        self.assertEqual(self.parent.children, [self.pred, self.src])
        self.assertEqual(self.src.removals, 0)
        self.assertEqual(result["results"][0]["handle"]["path"], "joint/arm")
        self.doc.AddUndo.assert_not_called()

    def test_already_inserted_replacement_is_not_inserted_twice(self):
        replacement = FakeObject("arm")

        def convert(**kwargs):
            self.src.Remove()
            self.src.alive = False
            self.doc.InsertObject(replacement, pred=self.pred)
            return [replacement]

        self.send.side_effect = convert
        self.run_command()
        self.assertEqual(self.parent.children, [self.pred, replacement])
        self.doc.AddUndo.assert_not_called()

    def test_in_place_command_keeps_source(self):
        self.send.return_value = True
        self.run_command("triangulate")
        self.assertEqual(self.parent.children, [self.pred, self.src])
        self.assertEqual(self.src.removals, 0)

    def test_failed_command_closes_undo_without_removing_source(self):
        self.send.return_value = False
        with self.assertRaisesRegex(RuntimeError, "returned False"):
            self.run_command()
        self.doc.EndUndo.assert_called_once()
        self.assertEqual(self.src.removals, 0)


if __name__ == "__main__":
    unittest.main()
