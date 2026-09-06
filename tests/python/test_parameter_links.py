from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

HANDLERS_ROOT = Path(__file__).resolve().parents[2] / "plugin/cinema4d_mcp_bridge/bridge/handlers"


class FakeDescLevel:
    def __init__(self, identifier, dtype, creator):
        self.id, self.dtype, self.creator = identifier, dtype, creator


class FakeDescID:
    def __init__(self, *levels):
        self.levels = levels

    def __getitem__(self, index):
        return self.levels[index]

    def GetDepth(self):
        return len(self.levels)


class FakeObject:
    def __init__(self, name):
        self.name = name
        self.type_id = 5140
        self.next = None
        self.description = []
        self.data = {}
        self.writes = []
        self.set_calls = []
        self.reject_set = False

    def GetName(self):
        return self.name

    def GetType(self):
        return self.type_id

    def GetTypeName(self):
        return "Null"

    def GetNext(self):
        return self.next

    def GetDown(self):
        return None

    def GetUp(self):
        return None

    def GetDescription(self, _flags):
        return self.description

    def key(self, key):
        return tuple(level.id for level in key.levels) if isinstance(key, FakeDescID) else (key,)

    def __getitem__(self, key):
        return self.data.get(self.key(key))

    def __setitem__(self, key, value):
        self.writes.append((key, value))
        self.data[self.key(key)] = value

    def SetParameter(self, descid, value, flags):
        self.set_calls.append((descid, value, flags))
        if self.reject_set:
            return False
        self[descid] = value
        return True


class FakeC4D(types.ModuleType):
    def __init__(self):
        super().__init__("c4d")
        self.DescID = FakeDescID
        self.DescLevel = FakeDescLevel
        self.BaseList2D = FakeObject
        self.BaseObject = FakeObject
        self.Vector = type("Vector", (), {})
        self.Tpython = 1022749
        self.Opython = 1023866
        self._constants = {}

    def __getattr__(self, name):
        value = self._constants.setdefault(name, 10000 + len(self._constants))
        setattr(self, name, value)
        return value


class ParameterLinksTest(unittest.TestCase):
    def setUp(self):
        self.c4d = FakeC4D()
        self.owner = FakeObject("Rig")
        self.target = FakeObject("Target")
        self.owner.next = self.target
        self.doc = types.SimpleNamespace(
            GetFirstObject=lambda: self.owner,
            StartUndo=Mock(),
            AddUndo=Mock(),
            EndUndo=Mock(),
        )
        documents = types.ModuleType("c4d.documents")
        documents.GetActiveDocument = lambda: self.doc
        self.c4d.documents = documents
        self.c4d.EventAdd = Mock()
        package = types.ModuleType("parameter_links_under_test")
        package.__path__ = []
        self.module_patch = patch.dict(
            sys.modules,
            {"c4d": self.c4d, "c4d.documents": documents, package.__name__: package},
        )
        self.module_patch.start()
        self.env_patch = patch.dict(os.environ, {"C4D_MCP_ENABLE_PYTHON_OPS": "0"})
        self.env_patch.start()
        self.helpers = self.load("_helpers")
        self.entities = self.load("entities")
        self.link_desc = FakeDescID(FakeDescLevel(1000, self.c4d.DTYPE_BASELISTLINK, 5140))
        self.scalar_desc = FakeDescID(FakeDescLevel(1001, self.c4d.DTYPE_REAL, 5140))
        self.owner.description = [({}, self.link_desc, None), ({}, self.scalar_desc, None)]
        self.owner.data = {(1000,): self.target, (1001,): 2.0}

    def tearDown(self):
        self.env_patch.stop()
        self.module_patch.stop()

    def load(self, name):
        spec = importlib.util.spec_from_file_location(
            f"parameter_links_under_test.{name}", HANDLERS_ROOT / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def call(self, values):
        return self.entities.handle_set_params(
            {"handle": {"kind": "object", "path": "/Rig"}, "values": values}
        )

    def assert_preflight_rejected(self, result):
        self.assertEqual(result["applied"], [])
        self.assertTrue(result["errors"])
        self.assertEqual(self.owner.writes, [])
        self.assertEqual(self.owner.set_calls, [])
        self.doc.StartUndo.assert_not_called()
        self.c4d.EventAdd.assert_not_called()

    def test_sets_and_clears_links_with_one_undo_group_per_call(self):
        for value in ({"link": {"kind": "object", "name": "Target"}}, {"link": None}):
            with self.subTest(value=value):
                result = self.call([{"path": 1000, "value": value}])
                self.assertEqual(result["errors"], [])
        self.assertIs(self.owner.set_calls[0][0], self.link_desc)
        self.assertIs(self.owner.set_calls[0][1], self.target)
        self.assertIsNone(self.owner.set_calls[1][1])
        self.assertEqual(self.owner.set_calls[0][2], self.c4d.DESCFLAGS_SET_NONE)
        self.assertIsNone(self.owner[1000])
        self.assertEqual(self.doc.StartUndo.call_count, 2)
        self.assertEqual(self.doc.AddUndo.call_count, 2)
        self.assertEqual(self.doc.EndUndo.call_count, 2)

    def test_missing_link_rejects_before_any_mixed_batch_write(self):
        result = self.call(
            [
                {"path": 1001, "value": 7.0},
                {"path": 1000, "value": {"link": {"kind": "object", "name": "Missing"}}},
            ]
        )
        self.assert_preflight_rejected(result)
        self.assertIs(self.owner[1000], self.target)
        self.assertEqual(self.owner[1001], 2.0)

    def test_wrong_destination_type_cannot_be_spoofed_by_a_dtype_hint(self):
        result = self.call(
            [
                {
                    "path": [[1001, self.c4d.DTYPE_BASELISTLINK, 0]],
                    "value": {"link": None},
                }
            ]
        )
        self.assert_preflight_rejected(result)
        self.assertIn("DTYPE_BASELISTLINK", result["errors"][0]["error"])

    def test_user_data_uses_actual_complete_descid_and_creator(self):
        descid = FakeDescID(
            FakeDescLevel(700, self.c4d.DTYPE_GROUP, 0),
            FakeDescLevel(1, self.c4d.DTYPE_BASELISTLINK, 100001),
        )
        self.owner.description.append(({}, descid, None))
        for path in (
            [700, 1],
            [[700, self.c4d.DTYPE_GROUP, 0], [1, self.c4d.DTYPE_BASELISTLINK, 100001]],
        ):
            result = self.call(
                [{"path": path, "value": {"link": {"kind": "object", "path": "/Target"}}}]
            )
            self.assertEqual(result["errors"], [])
            self.assertIs(self.owner.set_calls[-1][0], descid)
            self.assertIs(self.owner[descid], self.target)

    def test_malformed_wrapper_or_unknown_parameter_cannot_mutate(self):
        for path, value in (
            (1000, {"link": None, "extra": True}),
            (9999, {"link": None}),
            (1000, {"link": "Target"}),
        ):
            with self.subTest(path=path, value=value):
                self.assert_preflight_rejected(self.call([{"path": path, "value": value}]))

    def test_non_baselist_target_is_rejected_before_writes(self):
        resolver = self.entities._resolve_handle
        with patch.object(
            self.entities,
            "_resolve_handle",
            side_effect=lambda h: 42 if h.get("name") == "Bad" else resolver(h),
        ):
            result = self.call(
                [{"path": 1000, "value": {"link": {"kind": "object", "name": "Bad"}}}]
            )
        self.assert_preflight_rejected(result)

    def test_ambiguous_target_rejects_before_writes(self):
        self.target.next = FakeObject("Target")
        result = self.call(
            [{"path": 1000, "value": {"link": {"kind": "object", "name": "Target"}}}]
        )
        self.assert_preflight_rejected(result)
        self.assertIn("ambiguous", result["errors"][0]["error"])

    def test_setparameter_false_is_reported_as_an_error(self):
        self.owner.reject_set = True
        result = self.call([{"path": 1000, "value": {"link": None}}])
        self.assertEqual(result["applied"], [])
        self.assertIn("SetParameter", result["errors"][0]["error"])
        self.assertIs(self.owner[1000], self.target)
        self.doc.EndUndo.assert_called_once()

    def test_python_entity_gate_still_precedes_link_writes(self):
        self.owner.type_id = self.c4d.Opython
        with self.assertRaisesRegex(RuntimeError, "C4D_MCP_ENABLE_PYTHON_OPS"):
            self.call([{"path": 1000, "value": {"link": None}}])
        self.assertEqual(self.owner.set_calls, [])
        self.doc.StartUndo.assert_not_called()

    def test_primitive_requests_keep_the_existing_write_path(self):
        result = self.call([{"path": 1001, "value": 3.5}])
        self.assertEqual(result, {"applied": [{"path": [1001], "value": 3.5}], "errors": []})
        self.assertEqual(self.owner.set_calls, [])
        self.doc.StartUndo.assert_called_once()
        self.doc.EndUndo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
