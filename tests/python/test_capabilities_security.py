from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeDispatcher:
    def __init__(self, _plugin_id, handlers):
        self.handlers = handlers


class _FakeBridgeServer:
    def __init__(self, _dispatcher, host="127.0.0.1", port=18710, token=None):
        self._host = host
        self._port = port
        self._token = token or None

    def start(self):
        return None

    def stop(self):
        return None


class CapabilitiesSecurityTest(unittest.TestCase):
    def test_reports_server_startup_snapshot_after_environment_changes(self):
        c4d = types.ModuleType("c4d")
        documents = types.ModuleType("c4d.documents")
        plugins = types.ModuleType("c4d.plugins")
        plugins.MessageData = object
        plugins.RegisterMessagePlugin = lambda **_kwargs: True
        c4d.documents = documents
        c4d.plugins = plugins
        c4d.GetC4DVersion = lambda: 2025302
        c4d.C4DPL_ENDPROGRAM = 1

        bridge = types.ModuleType("bridge")
        bridge.__path__ = []
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = []
        helpers = types.ModuleType("bridge.handlers._helpers")
        helpers._require_writable_path = lambda path, _roots: path
        dispatcher = types.ModuleType("bridge.dispatcher")
        dispatcher.Dispatcher = _FakeDispatcher
        server = types.ModuleType("bridge.server")
        server.BridgeServer = _FakeBridgeServer

        fake_modules = {
            "c4d": c4d,
            "c4d.documents": documents,
            "c4d.plugins": plugins,
            "bridge": bridge,
            "bridge.handlers": handlers,
            "bridge.handlers._helpers": helpers,
            "bridge.dispatcher": dispatcher,
            "bridge.server": server,
        }
        startup_environment = {
            "C4D_MCP_HOST": "127.0.0.1",
            "C4D_MCP_TOKEN": "startup-token",
            "C4D_MCP_ENABLE_EXEC_PYTHON": "",
        }

        with (
            patch.dict(sys.modules, fake_modules),
            patch.dict(os.environ, startup_environment, clear=False),
        ):
            basics = self._load_module(
                "bridge.handlers.basics",
                REPO_ROOT / "plugin/cinema4d_mcp_bridge/bridge/handlers/basics.py",
            )
            handlers.HANDLERS = {"get_capabilities": basics.handle_get_capabilities}
            configure = getattr(basics, "configure_security_snapshot", None)
            if configure is not None:
                handlers.configure_security_snapshot = configure

            entrypoint = self._load_pyp(
                "cinema4d_mcp_bridge_entrypoint",
                REPO_ROOT / "plugin/cinema4d_mcp_bridge/cinema4d_mcp_bridge.pyp",
            )
            plugin = entrypoint.MCPBridgePlugin()
            self.assertEqual(plugin._server._host, "127.0.0.1")
            self.assertEqual(plugin._server._token, "startup-token")

            os.environ["C4D_MCP_HOST"] = "0.0.0.0"
            os.environ["C4D_MCP_TOKEN"] = ""
            os.environ["C4D_MCP_ENABLE_EXEC_PYTHON"] = "true"
            result = plugin._dispatcher.handlers["get_capabilities"]({})

        self.assertEqual(
            result["security"],
            {"loopback": True, "token_required": True, "exec_python": True},
        )

    @staticmethod
    def _load_module(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _load_pyp(name: str, path: Path):
        loader = SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        if spec is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
