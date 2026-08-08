from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeC4D(types.ModuleType):
    def __init__(self):
        super().__init__("c4d")
        self.BaseObject = type("BaseObject", (), {})
        self.Vector = type("Vector", (), {})
        self._constants = {}

    def __getattr__(self, name):
        value = self._constants.setdefault(name, 1000 + len(self._constants))
        setattr(self, name, value)
        return value


class JsonSafeTest(unittest.TestCase):
    def test_preserves_json_arrays_nested_inside_batch_results(self):
        c4d = _FakeC4D()
        documents = types.ModuleType("c4d.documents")
        c4d.documents = documents

        with patch.dict(sys.modules, {"c4d": c4d, "c4d.documents": documents}):
            helpers = self._load_module(
                "c4d_mcp_helpers_under_test",
                REPO_ROOT / "plugin/cinema4d_mcp_bridge/bridge/handlers/_helpers.py",
            )

        payload = {
            "status": "ok",
            "result": {
                "results": [
                    {
                        "index": 3,
                        "op": "sample_transform",
                        "result": {
                            "samples": [
                                {
                                    "frame": 0,
                                    "pos": [100.0, 20.0, -30.0],
                                    "rot": [0.0, 0.0, 0.0],
                                }
                            ]
                        },
                    }
                ]
            },
        }

        safe = helpers._json_safe(payload)

        sample = safe["result"]["results"][0]["result"]["samples"][0]
        self.assertEqual(sample["pos"], [100.0, 20.0, -30.0])
        self.assertEqual(sample["rot"], [0.0, 0.0, 0.0])

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
