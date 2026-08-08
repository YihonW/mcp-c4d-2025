"""Lightweight handlers: ping, undo, reset_scene, render."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from typing import Any

import c4d
from c4d import documents

from ._helpers import _require_writable_path

_BRIDGE_VERSION = "0.4.0"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _available_renderer_plugins() -> list[dict[str, Any]]:
    """Return video-post identifiers when the optional plugin API is present."""
    plugin_api = getattr(c4d, "plugins", None)
    filter_plugins = getattr(plugin_api, "FilterPluginList", None)
    find_plugin = getattr(plugin_api, "FindPlugin", None)
    plugin_type = getattr(c4d, "PLUGINTYPE_VIDEOPOST", None)
    if not callable(filter_plugins) or not isinstance(plugin_type, int):
        return []

    try:
        candidates = filter_plugins(plugin_type, True) or []
    except Exception:
        return []

    detected: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            get_id = getattr(candidate, "GetID", None)
            if not callable(get_id):
                continue
            plugin_id = int(get_id())
            plugin = candidate
            if callable(find_plugin):
                plugin = find_plugin(plugin_id, plugin_type)
                if plugin is None:
                    continue
            get_name = getattr(plugin, "GetName", None)
            name = get_name() if callable(get_name) else ""
            detected.append({"id": plugin_id, "name": str(name or "")})
        except Exception:
            continue
    return detected


def handle_get_capabilities(_params: dict[str, Any]) -> dict[str, Any]:
    """Describe the running bridge without assuming optional SDK symbols."""
    host = os.environ.get("C4D_MCP_HOST") or os.environ.get("C4D_MCP_BRIDGE_HOST") or "127.0.0.1"
    token = (os.environ.get("C4D_MCP_TOKEN") or "").strip()
    exec_python = os.environ.get("C4D_MCP_ENABLE_EXEC_PYTHON", "").strip().lower() in _TRUTHY

    base_document = getattr(documents, "BaseDocument", None)
    version = sys.version_info
    return {
        "c4d_version": c4d.GetC4DVersion(),
        "python_version": f"{version.major}.{version.minor}.{version.micro}",
        "platform": sys.platform,
        "bridge_version": _BRIDGE_VERSION,
        "security": {
            "loopback": host in _LOOPBACK_HOSTS,
            "token_required": bool(token),
            "exec_python": exec_python,
        },
        "groups": ["basics", "entities", "transform"],
        "features": {
            "node_materials": getattr(c4d, "NodeMaterial", None) is not None,
            "scene_nodes": callable(getattr(base_document, "GetSceneRepository", None)),
        },
        "plugins": _available_renderer_plugins(),
    }


def handle_ping(_params: dict[str, Any]) -> dict[str, Any]:
    return {"pong": True, "c4d_version": c4d.GetC4DVersion()}


def handle_undo(params: dict[str, Any]) -> dict[str, Any]:
    """Pop up to ``steps`` entries off the active document's undo stack.

    Stops early if the undo stack is exhausted. Returns the number of steps
    actually performed so callers can detect the stack-empty case.
    """
    steps = int(params.get("steps", 1))
    if steps < 1:
        raise ValueError("steps must be >= 1")
    doc = documents.GetActiveDocument()
    if doc is None:
        raise RuntimeError("no active document")
    done = 0
    for _ in range(steps):
        if not doc.DoUndo(True):
            break
        done += 1
    c4d.EventAdd()
    return {"steps_performed": done, "requested": steps}


def handle_reset_scene(params: dict[str, Any]) -> dict[str, Any]:
    """Swap in a fresh empty document, dropping the previous doc entirely.

    Cheap way for test suites and agent workflows to get a clean slate
    without routing through ``exec_python`` (opt-in) or dozens of
    ``remove_entity`` RPCs. Optionally prefix-filtered: when ``prefix`` is
    supplied, we only clear objects / materials / render data whose name
    starts with that prefix and leave the rest of the scene alone.

    params:
      prefix:        optional name prefix. When set, only matching top-level
                     objects / materials / non-active render data are
                     removed. When omitted, the current document is replaced
                     with a brand-new empty BaseDocument.
      keep_active_rd: bool (default True). Only honoured in prefix mode —
                     protects the currently-active render data from deletion
                     regardless of its name.
    """
    doc = documents.GetActiveDocument()
    if doc is None:
        return {"reset": False, "reason": "no active document"}

    prefix = params.get("prefix")
    keep_active_rd = bool(params.get("keep_active_rd", True))

    if isinstance(prefix, str) and prefix:
        removed = {"objects": 0, "materials": 0, "render_data": 0, "takes": 0}

        # Objects — walk top-level siblings and drop any matching the prefix.
        obj = doc.GetFirstObject()
        while obj is not None:
            nxt = obj.GetNext()
            if obj.GetName().startswith(prefix):
                obj.Remove()
                removed["objects"] += 1
            obj = nxt

        # Materials.
        mat = doc.GetFirstMaterial()
        while mat is not None:
            nxt = mat.GetNext()
            if mat.GetName().startswith(prefix):
                mat.Remove()
                removed["materials"] += 1
            mat = nxt

        # Render data — skip the active one even if it matches.
        active_rd = doc.GetActiveRenderData() if keep_active_rd else None
        rd = doc.GetFirstRenderData()
        while rd is not None:
            nxt = rd.GetNext()
            if rd is not active_rd and rd.GetName().startswith(prefix):
                rd.Remove()
                removed["render_data"] += 1
            rd = nxt

        # Non-main takes.
        td = doc.GetTakeData()
        if td is not None:

            def drop_matching(parent):
                c = parent.GetDown()
                while c is not None:
                    nxt = c.GetNext()
                    drop_matching(c)
                    if not c.IsMain() and c.GetName().startswith(prefix):
                        td.DeleteTake(c)
                        removed["takes"] += 1
                    c = nxt

            drop_matching(td.GetMainTake())
            td.SetCurrentTake(td.GetMainTake())

        # Flush the undo stack so subsequent tests don't pay the cost of
        # replaying a long history of animated-object removals.
        with contextlib.suppress(Exception):
            doc.FlushUndoBuffer()

        c4d.EventAdd()
        return {"reset": True, "prefix": prefix, "removed": removed}

    # No prefix → replace the whole document.
    new_doc = c4d.documents.BaseDocument()
    documents.InsertBaseDocument(new_doc)
    documents.SetActiveDocument(new_doc)
    with contextlib.suppress(Exception):
        documents.KillDocument(doc)
    c4d.EventAdd()
    return {"reset": True, "replaced_document": True}


def handle_render(params: dict[str, Any]) -> dict[str, Any]:
    """Render the active document using its currently-active render data.

    Width / height / renderer etc. come from the active RenderData — adjust
    it via ``create_render_data`` + ``set_params`` beforehand if needed.
    """
    doc = documents.GetActiveDocument()
    if doc is None:
        raise RuntimeError("no active document")

    rd = doc.GetActiveRenderData().GetClone()
    if rd is None:
        raise RuntimeError("failed to clone active render data")

    xres = int(rd[c4d.RDATA_XRES])
    yres = int(rd[c4d.RDATA_YRES])

    bitmap = c4d.bitmaps.MultipassBitmap(xres, yres, c4d.COLORMODE_RGB)
    if bitmap is None:
        raise RuntimeError("failed to allocate render bitmap")
    # Add an internal alpha+straight-alpha channel. Required for many renderers
    # (physical/redshift/octane) even though COLORMODE_RGB itself has no alpha.
    bitmap.AddChannel(True, True)

    result = documents.RenderDocument(
        doc,
        rd.GetDataInstance(),
        bitmap,
        c4d.RENDERFLAGS_EXTERNAL,
    )
    if result != c4d.RENDERRESULT_OK:
        raise RuntimeError(f"render failed with code {result}")

    raw_output = params.get("output_path")
    if isinstance(raw_output, str) and raw_output:
        # Same abs-path + parent-dir rules as save_document: keep path handling
        # uniform so LLM-driven relative paths can't land in the C4D cwd.
        output_path: str = _require_writable_path(raw_output)
    else:
        fd, output_path = tempfile.mkstemp(prefix="c4d_mcp_render_", suffix=".png")
        os.close(fd)

    save_result = bitmap.Save(output_path, c4d.FILTER_PNG)
    if save_result != c4d.IMAGERESULT_OK:
        raise RuntimeError(f"failed to save image to {output_path} (code {save_result})")

    return {
        "path": output_path,
        "width": xres,
        "height": yres,
    }
