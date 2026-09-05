from __future__ import annotations

import contextlib
import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from redshift_fakes import RS_RENDERER_ID, make_c4d_runtime, make_redshift_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin" / "cinema4d_mcp_bridge"


class FakeAov:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def GetParameter(self, parameter):
        return self.values.get(parameter)

    def SetParameter(self, parameter, value):
        self.values[parameter] = value

    def GetClone(self):
        return FakeAov(self.values)

    def GetDataInstance(self):
        return FakeContainer(self.values)


class RejectingAov(FakeAov):
    def SetParameter(self, parameter, value):
        return False


class FakeContainer:
    def __init__(self, values):
        self.values = values

    def GetCount(self):
        return len(self.values)

    def GetIndexId(self, index):
        return list(self.values)[index]

    def GetIndexData(self, index):
        return self.values[list(self.values)[index]]


class FakeRenderData:
    def __init__(self, name):
        self.name = name
        self.next = None

    def GetName(self):
        return self.name

    def GetNext(self):
        return self.next

    def GetDown(self):
        return None


class FakeAovDocument:
    def __init__(self, name, render_data):
        self.name = name
        self.render_data = render_data
        self.next = None

    def GetDocumentName(self):
        return self.name

    def GetNext(self):
        return self.next

    def GetActiveRenderData(self):
        return self.render_data

    def GetFirstRenderData(self):
        return self.render_data


class RedshiftAovsTest(unittest.TestCase):
    def test_plural_sdk_symbols_expose_reflection_refraction_and_normal_aliases(self):
        self.c4d.REDSHIFT_AOV_TYPE_REFLECTIONS = 9
        self.c4d.REDSHIFT_AOV_TYPE_REFRACTIONS = 12
        self.c4d.REDSHIFT_AOV_TYPE_NORMALS = 20
        module = importlib.import_module("bridge.handlers.redshift.aovs")
        aliases = module.aov_type_aliases()
        self.assertEqual(aliases.get("reflection"), 9)
        self.assertEqual(aliases.get("refraction"), 12)
        self.assertEqual(aliases.get("normal"), 20)

    def setUp(self):
        self.c4d, self.documents, self.document_state, _ = make_c4d_runtime(
            document_names=["main"], plugins={RS_RENDERER_ID}
        )
        self.render_data = FakeRenderData("Active")
        self.alt_render_data = FakeRenderData("Final")
        self.render_data.next = self.alt_render_data
        self.document = FakeAovDocument("main", self.render_data)
        self.document_state.items = [self.document]
        self.document_state.active = self.document
        self._install_aov_symbols()
        self.redshift = make_redshift_runtime()
        self.video_posts = {self.render_data: object(), self.alt_render_data: object()}
        self.aovs = []
        self.set_calls = []
        self.fail_first_set = False
        self.return_false_first_set = False
        self.video_post_calls = []

        def find_video_post(render_data, _renderer):
            self.video_post_calls.append(render_data)
            return self.video_posts[render_data]

        self.redshift.FindAddVideoPost = find_video_post
        self.redshift.RendererGetAOVs = lambda _video_post: list(self.aovs)

        def set_aovs(_video_post, aovs):
            self.set_calls.append(list(aovs))
            if self.fail_first_set and len(self.set_calls) == 1:
                raise RuntimeError("set failed")
            if self.return_false_first_set and len(self.set_calls) == 1:
                return False
            self.aovs = list(aovs)
            return True

        self.redshift.RendererSetAOVs = set_aovs
        self.redshift.RSAOV = FakeAov
        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        maxon = types.ModuleType("maxon")
        parent_helpers = types.ModuleType("bridge.handlers._helpers")
        parent_helpers._require_writable_path = self._require_writable_path
        parent_helpers._require_abs_path = lambda value, **_kwargs: str(value)
        self.modules = {
            "c4d": self.c4d,
            "c4d.documents": self.documents,
            "maxon": maxon,
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

    def _install_aov_symbols(self):
        symbols = {
            "REDSHIFT_AOV_TYPE": 1000,
            "REDSHIFT_AOV_NAME": 1001,
            "REDSHIFT_AOV_ENABLED": 1002,
            "REDSHIFT_AOV_MULTIPASS_ENABLED": 1003,
            "REDSHIFT_AOV_FILE_ENABLED": 1004,
            "REDSHIFT_AOV_FILE_PATH": 1005,
            "REDSHIFT_AOV_TYPE_BEAUTY": 10,
            "REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING": 11,
            "REDSHIFT_AOV_TYPE_DEPTH": 12,
        }
        for name, value in symbols.items():
            setattr(self.c4d, name, value)

    @staticmethod
    def _require_writable_path(value):
        path = str(value)
        if not os.path.isabs(path):
            raise ValueError("output path must be absolute")
        return path

    def _load(self):
        return importlib.import_module("bridge.handlers.redshift.aovs")

    def _aov(self, type_value=10, name="Beauty", **overrides):
        values = {
            self.c4d.REDSHIFT_AOV_TYPE: type_value,
            self.c4d.REDSHIFT_AOV_NAME: name,
            self.c4d.REDSHIFT_AOV_ENABLED: True,
            self.c4d.REDSHIFT_AOV_MULTIPASS_ENABLED: True,
            self.c4d.REDSHIFT_AOV_FILE_ENABLED: False,
            self.c4d.REDSHIFT_AOV_FILE_PATH: "",
            9001: 1.25,
            9002: "safe",
            9003: object(),
        }
        values.update(overrides)
        return FakeAov(values)

    def test_list_serializes_active_render_data_and_safe_primitive_parameters(self):
        self.aovs = [self._aov()]
        aovs = self._load()

        result = aovs.handle_rs_list_aovs({})

        self.assertEqual(result["render_data"], {"kind": "render_data", "name": "Active"})
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["aovs"],
            [
                {
                    "index": 0,
                    "type": 10,
                    "type_alias": "beauty",
                    "name": "Beauty",
                    "enabled": True,
                    "multipass_enabled": True,
                    "direct_file_enabled": False,
                    "direct_file_path": "",
                    "params": {"9001": 1.25, "9002": "safe"},
                }
            ],
        )

    def test_list_serializes_an_empty_aov_list(self):
        aovs = self._load()

        result = aovs.handle_rs_list_aovs({})

        self.assertEqual(result["aovs"], [])
        self.assertEqual(result["count"], 0)

    def test_list_uses_exact_named_render_data(self):
        self.aovs = [self._aov(name="FinalBeauty")]
        aovs = self._load()

        result = aovs.handle_rs_list_aovs({"render_data_name": "Final"})

        self.assertEqual(result["render_data"]["name"], "Final")
        self.assertEqual(result["aovs"][0]["name"], "FinalBeauty")

    def test_capabilities_expose_only_present_public_aov_aliases(self):
        capabilities = importlib.import_module("bridge.handlers.redshift.capabilities")

        aliases = capabilities.handle_rs_get_capabilities({})["aov_api"]["aliases"]

        self.assertEqual(aliases, {"beauty": 10, "diffuse_lighting": 11, "depth": 12})

    def test_upsert_normalizes_existing_alias_or_raw_type_and_creates(self):
        aovs = self._load()

        created = aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty"})
        raw_created = aovs.handle_rs_upsert_aov({"type": 44, "name": "Custom"})

        self.assertTrue(created["created"])
        self.assertEqual(created["rollback"], "not_needed")
        self.assertEqual(created["aov"]["type"], 10)
        self.assertTrue(raw_created["created"])
        self.assertEqual(raw_created["aov"]["type"], 44)
        self.assertEqual(len(self.set_calls), 2)

    def test_upsert_updates_exact_type_and_name_from_an_independent_proposed_snapshot(self):
        original = self._aov()
        self.aovs = [original]
        aovs = self._load()

        result = aovs.handle_rs_upsert_aov(
            {"type": "beauty", "name": "Beauty", "enabled": False, "params": {"9001": 9}}
        )

        self.assertFalse(result["created"])
        self.assertFalse(result["aov"]["enabled"])
        self.assertEqual(result["aov"]["params"]["9001"], 9)
        self.assertIsNot(self.set_calls[0][0], original)
        self.assertTrue(original.GetParameter(self.c4d.REDSHIFT_AOV_ENABLED))
        self.assertEqual(original.GetParameter(9001), 1.25)

    def test_upsert_rejects_failed_parameter_write_before_list_mutation(self):
        self.redshift.RSAOV = RejectingAov
        aovs = self._load()

        with self.assertRaisesRegex(RuntimeError, "failed to set AOV parameter"):
            aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty"})

        self.assertEqual(self.set_calls, [])

    def test_upsert_rejects_ambiguous_duplicate_matches_before_mutation(self):
        self.aovs = [self._aov(), self._aov()]
        aovs = self._load()

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty"})

        self.assertEqual(self.set_calls, [])

    def test_upsert_rejects_unknown_alias_before_mutation(self):
        aovs = self._load()

        with self.assertRaisesRegex(ValueError, "unknown AOV type alias"):
            aovs.handle_rs_upsert_aov({"type": "reflection", "name": "Reflection"})

        self.assertEqual(self.set_calls, [])

    def test_upsert_validates_direct_output_path_and_raw_params_before_mutation(self):
        aovs = self._load()

        with self.assertRaisesRegex(ValueError, "absolute"):
            aovs.handle_rs_upsert_aov(
                {
                    "type": "beauty",
                    "name": "Beauty",
                    "direct_file_enabled": True,
                    "direct_file_path": "relative.exr",
                }
            )
        with self.assertRaisesRegex(ValueError, "params keys"):
            aovs.handle_rs_upsert_aov(
                {"type": "beauty", "name": "Beauty", "params": {"not-an-id": 1}}
            )
        with self.assertRaisesRegex(ValueError, "primitive"):
            aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty", "params": {"9001": []}})
        with self.assertRaisesRegex(ValueError, "managed AOV parameter"):
            aovs.handle_rs_upsert_aov(
                {
                    "type": "beauty",
                    "name": "Beauty",
                    "params": {str(self.c4d.REDSHIFT_AOV_TYPE): 44},
                }
            )
        self.assertEqual(self.set_calls, [])

    def test_missing_aov_api_rejects_before_render_data_or_mutation(self):
        del self.redshift.RendererSetAOVs
        aovs = self._load()

        with self.assertRaisesRegex(RuntimeError, "aov_api"):
            aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty"})

        self.assertEqual(self.set_calls, [])

    def test_set_failure_restores_untouched_original_list_and_reports_rollback(self):
        original = self._aov()
        self.aovs = [original]
        self.fail_first_set = True
        aovs = self._load()

        with self.assertRaisesRegex(RuntimeError, "rollback=succeeded"):
            aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty", "enabled": False})

        self.assertEqual(len(self.set_calls), 2)
        self.assertIs(self.set_calls[1][0], original)
        self.assertTrue(original.GetParameter(self.c4d.REDSHIFT_AOV_ENABLED))

    def test_false_set_result_restores_original_and_does_not_report_success(self):
        original = self._aov()
        self.aovs = [original]
        self.return_false_first_set = True
        aovs = self._load()

        with self.assertRaisesRegex(RuntimeError, "rollback=succeeded"):
            aovs.handle_rs_upsert_aov({"type": "beauty", "name": "Beauty", "enabled": False})

        self.assertEqual(len(self.set_calls), 2)
        self.assertIs(self.set_calls[1][0], original)

    def test_remove_rejects_out_of_range_and_stale_index_before_mutation(self):
        self.aovs = [self._aov()]
        aovs = self._load()

        with self.assertRaisesRegex(ValueError, "out of range"):
            aovs.handle_rs_remove_aov(
                {"index": 2, "expected_name": "Beauty", "expected_type": "beauty"}
            )
        with self.assertRaisesRegex(ValueError, "stale AOV index"):
            aovs.handle_rs_remove_aov(
                {"index": 0, "expected_name": "Old Beauty", "expected_type": "beauty"}
            )
        with self.assertRaisesRegex(ValueError, "stale AOV index"):
            aovs.handle_rs_remove_aov(
                {"index": 0, "expected_name": "Beauty", "expected_type": "depth"}
            )

        self.assertEqual(self.set_calls, [])

    def test_remove_uses_one_fresh_snapshot_and_returns_the_removed_record(self):
        beauty = self._aov()
        depth = self._aov(type_value=12, name="Depth")
        self.aovs = [beauty, depth]
        aovs = self._load()

        result = aovs.handle_rs_remove_aov(
            {"index": 0, "expected_name": "Beauty", "expected_type": "beauty"}
        )

        self.assertEqual(result["removed"]["name"], "Beauty")
        self.assertEqual(result["removed"]["type"], 10)
        self.assertEqual(result["remaining_count"], 1)
        self.assertEqual(result["rollback"], "not_needed")
        self.assertEqual(self.set_calls, [[depth]])

    def test_clear_requires_document_and_exact_force_before_video_post_access(self):
        aovs = self._load()

        with self.assertRaisesRegex(ValueError, "document_name"):
            aovs.handle_rs_clear_aovs({"force": True})
        with self.assertRaisesRegex(ValueError, "force must be true"):
            aovs.handle_rs_clear_aovs({"document_name": "main", "force": False})

        self.assertEqual(self.video_post_calls, [])
        self.assertEqual(self.set_calls, [])

    def test_clear_removes_all_aovs_and_returns_pre_mutation_records(self):
        self.aovs = [self._aov(), self._aov(type_value=12, name="Depth")]
        aovs = self._load()

        result = aovs.handle_rs_clear_aovs({"document_name": "main", "force": True})

        self.assertEqual([record["name"] for record in result["removed"]], ["Beauty", "Depth"])
        self.assertEqual(result["remaining_count"], 0)
        self.assertEqual(result["rollback"], "not_needed")
        self.assertEqual(self.set_calls, [[]])

    def test_clear_failure_restores_independent_clones_and_reports_succeeded(self):
        original = self._aov()
        self.aovs = [original]
        self.fail_first_set = True
        aovs = self._load()

        with self.assertRaisesRegex(RuntimeError, "rollback=succeeded"):
            aovs.handle_rs_clear_aovs({"document_name": "main", "force": True})

        self.assertEqual(len(self.set_calls), 2)
        self.assertIsNot(self.set_calls[1][0], original)

    def test_clear_clone_less_failure_reports_partial_rollback(self):
        original = self._aov()
        original.GetClone = None
        self.aovs = [original]
        self.fail_first_set = True
        aovs = self._load()

        with self.assertRaisesRegex(RuntimeError, "rollback=partial"):
            aovs.handle_rs_clear_aovs({"document_name": "main", "force": True})

        self.assertEqual(len(self.set_calls), 2)
        self.assertIsNot(self.set_calls[1][0], original)

    def test_remove_restores_the_previous_active_document(self):
        target = FakeAovDocument("target", FakeRenderData("Target"))
        self.document.next = target
        self.document_state.items = [self.document, target]
        self.video_posts[target.render_data] = object()
        self.aovs = [self._aov()]
        aovs = self._load()

        aovs.handle_rs_remove_aov(
            {
                "document_name": "target",
                "index": 0,
                "expected_name": "Beauty",
                "expected_type": "beauty",
            }
        )

        self.assertIs(self.document_state.active, self.document)


if __name__ == "__main__":
    unittest.main()
