from __future__ import annotations

import contextlib
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from redshift_fakes import (
    RS_RENDERER_ID,
    make_c4d_runtime,
    make_maxon_runtime,
    make_redshift_runtime,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin" / "cinema4d_mcp_bridge"
MATERIAL_ASSETS = (
    "com.redshift3d.redshift4c4d.node.output",
    "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
)


class RedshiftCapabilitiesTest(unittest.TestCase):
    def setUp(self):
        self.c4d, self.documents, self.document_state, self.plugin_lookup = make_c4d_runtime(
            document_names=["main", "target"]
        )
        self.maxon, self.repository = make_maxon_runtime(MATERIAL_ASSETS)
        self.redshift = make_redshift_runtime()
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

    def _load_capabilities(self):
        return importlib.import_module("bridge.handlers.redshift.capabilities")

    def _load_helpers(self):
        return importlib.import_module("bridge.handlers.redshift._helpers")

    def test_missing_redshift_module_is_reported_without_import_failure(self):
        del sys.modules["redshift"]
        capabilities = self._load_capabilities()

        result = capabilities.handle_rs_get_capabilities({})

        self.assertFalse(result["module"]["supported"])
        self.assertIn("redshift module", result["module"]["reason"])

    def test_complete_runtime_reports_renderer_nodes_aovs_lights_camera_and_render(self):
        capabilities = self._load_capabilities()

        result = capabilities.handle_rs_get_capabilities({})

        self.assertEqual(result["renderer"], {"supported": True, "id": RS_RENDERER_ID})
        self.assertEqual(result["node_space"]["id"], "com.redshift3d.redshift4c4d.class.nodespace")
        self.assertGreaterEqual(result["node_space"]["node_template_count"], 1)
        self.assertTrue(result["aov_api"]["supported"])
        self.assertTrue(result["lights"]["types"]["area"]["supported"])
        self.assertTrue(result["camera"]["supported"])
        self.assertTrue(result["render"]["supported"])

    def test_missing_optional_symbol_disables_only_its_feature(self):
        del self.redshift.RendererSetAOVs
        capabilities = self._load_capabilities()

        result = capabilities.handle_rs_get_capabilities({})

        self.assertFalse(result["aov_api"]["supported"])
        self.assertTrue(result["materials"]["supported"])

    def test_resolve_document_rejects_zero_and_duplicate_names_before_activation(self):
        helpers = self._load_helpers()

        with self.assertRaisesRegex(ValueError, "not found"):
            helpers.resolve_document("missing", required=True)
        self.assertEqual(self.document_state.active_changes, [])

        duplicate = self.document_state.items[1].__class__("target")
        self.document_state.items[-1].next = duplicate
        with self.assertRaisesRegex(ValueError, "document_name must be unique"):
            helpers.resolve_document("target", required=True)
        self.assertEqual(self.document_state.active_changes, [])

    def test_document_scope_restores_previous_document_after_success_and_exception(self):
        helpers = self._load_helpers()
        previous = self.document_state.active

        with helpers.document_scope("target", required=True) as target:
            self.assertEqual(target.GetDocumentName(), "target")
            self.assertIs(self.document_state.active, target)
        self.assertIs(self.document_state.active, previous)

        with (
            self.assertRaisesRegex(RuntimeError, "handler failed"),
            helpers.document_scope("target", required=True),
        ):
            raise RuntimeError("handler failed")
        self.assertIs(self.document_state.active, previous)
        self.assertEqual(
            [document.GetDocumentName() for document in self.document_state.active_changes],
            ["target", "main", "target", "main"],
        )


if __name__ == "__main__":
    unittest.main()
