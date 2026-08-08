"""Script-style handlers: exec_python, call_command, list_plugins, batch."""

from __future__ import annotations

import contextlib
import io
import os
import traceback
from typing import Any

import c4d
from c4d import documents

from ..log import log as _log
from ._helpers import (
    _describe_params,
    _dump_container,
    _find_material,
    _find_object,
    _find_object_by_path,
    _find_render_data,
    _find_tag,
    _find_take,
    _find_videopost,
    _json_safe,
    _plugin_type_alias,
    _resolve_handle,
    _shader_at,
)

_SCOPED_BATCH_FORBIDDEN_OPS = frozenset(
    {
        "set_active_document",
        "new_document",
        "open_document",
        "close_document",
        "reset_scene",
        "exec_python",
        "call_command",
    }
)


def _exec_python_enabled() -> bool:
    """Return True when the operator has opted IN to exec_python."""
    flag = os.environ.get("C4D_MCP_ENABLE_EXEC_PYTHON", "")
    return flag.strip().lower() in ("1", "true", "yes", "on")


def handle_exec_python(params: dict[str, Any]) -> dict[str, Any]:
    """Run arbitrary Python on C4D's main thread.

    Globals provided: ``c4d``, ``documents``, ``doc`` (active document),
    ``op`` (first selected object). Assign to ``result`` inside the code to
    return a value. Both ``stdout`` and ``stderr`` are captured.
    """
    if not _exec_python_enabled():
        raise RuntimeError(
            "exec_python is disabled on this C4D instance "
            "(C4D_MCP_ENABLE_EXEC_PYTHON is not set). Set the env var to 1 in the "
            "Cinema 4D launch environment and restart to enable."
        )

    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("parameter 'code' (str) is required")

    # Audit trail — the full code body goes to the local bridge log so
    # prompt-injection or LLM misuse can be reconstructed after the fact.
    # The log never leaves the local machine (see log.py); the code body is
    # not echoed back to the MCP client.
    _log(f"exec_python: begin ({len(code)} chars)\n----- code -----\n{code}\n----- end -----")
    doc = documents.GetActiveDocument()
    op = doc.GetActiveObject() if doc is not None else None

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    ns: dict[str, Any] = {
        "__name__": "__c4d_mcp_exec__",
        "c4d": c4d,
        "documents": documents,
        "doc": doc,
        "op": op,
        # Generic helpers (same ones exposed as MCP tools).
        "find_object": _find_object,
        "find_object_by_path": _find_object_by_path,
        "find_render_data": _find_render_data,
        "find_take": _find_take,
        "find_material": _find_material,
        "find_tag": _find_tag,
        "find_videopost": _find_videopost,
        "shader_at": _shader_at,
        "describe": _describe_params,
        "dump_container": _dump_container,
        "resolve_handle": _resolve_handle,
        "result": None,
    }

    error: str | None = None
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exec(compile(code, "<mcp_exec>", "exec"), ns)
        _log("exec_python: exec completed")
    except Exception:
        error = traceback.format_exc()
        _log(f"exec_python: exec raised\n{error}")

    return {
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "result": _json_safe(ns.get("result")),
        "error": error,
    }


def handle_call_command(params: dict[str, Any]) -> dict[str, Any]:
    """Invoke a Cinema 4D command by plugin id (``c4d.CallCommand``).

    CallCommand runs synchronously in many cases (e.g. Render to Picture
    Viewer). Long-running commands may exceed the default 30s tool timeout —
    pass a larger ``timeout_ms`` via exec_python if needed.
    """
    cid = params.get("command_id")
    if cid is None:
        raise ValueError("command_id required")
    cid = int(cid)
    subid_raw = params.get("subid")
    subid = int(subid_raw) if subid_raw is not None else 0

    name = ""
    with contextlib.suppress(Exception):
        name = c4d.GetCommandName(cid) or ""
    try:
        enabled = bool(c4d.IsCommandEnabled(cid))
    except Exception:
        enabled = None

    c4d.CallCommand(cid, subid)
    c4d.EventAdd()
    return {"command_id": cid, "subid": subid, "name": name, "was_enabled": enabled}


def _enumerate_plugins(
    plugin_type: int,
    name_pattern: str | None = None,
    plugin_pattern: str | None = None,
) -> list[dict[str, Any]]:
    """Enumerate plugins of ``plugin_type`` and attach host-plugin attribution.

    Each entry includes ``plugin`` (parent folder of the plugin binary) and
    ``plugin_file`` (binary basename), so commands with generic names like
    "Convert Materials" can be traced back to their owning plugin.
    """
    import re

    name_rx = re.compile(name_pattern) if name_pattern else None
    plugin_rx = re.compile(plugin_pattern) if plugin_pattern else None

    out: list[dict[str, Any]] = []
    for p in c4d.plugins.FilterPluginList(plugin_type, True):
        nm = p.GetName() or ""
        if name_rx and not name_rx.search(nm):
            continue
        try:
            fn = p.GetFilename() or ""
        except Exception:
            fn = ""
        plugin_file = os.path.basename(fn) if fn else ""
        plugin_dir = os.path.basename(os.path.dirname(fn)) if fn else ""
        if plugin_rx and not (plugin_rx.search(plugin_dir) or plugin_rx.search(plugin_file)):
            continue
        out.append(
            {
                "id": p.GetID(),
                "name": nm,
                "plugin": plugin_dir,
                "plugin_file": plugin_file,
            }
        )
    out.sort(key=lambda e: (e["plugin"].lower(), e["name"].lower()))
    return out


def handle_list_plugins(params: dict[str, Any]) -> dict[str, Any]:
    """List plugins of any ``PLUGINTYPE`` (command, material, shader, ...).

    Unified plugin discovery for commands, objects, materials, shaders, video
    posts, scene loaders etc. Entries include ``plugin`` (parent folder of the
    binary) and ``plugin_file`` (basename) so plugins with generic display
    names like "Convert Materials" can be attributed to their host plugin.
    """
    plugin_type_arg = params.get("plugin_type", "command")
    if isinstance(plugin_type_arg, str):
        plugin_type = _plugin_type_alias(plugin_type_arg)
    elif isinstance(plugin_type_arg, int):
        plugin_type = plugin_type_arg
    else:
        raise ValueError(
            f"plugin_type must be a string alias or int, got {type(plugin_type_arg).__name__}"
        )
    out = _enumerate_plugins(
        plugin_type,
        name_pattern=params.get("name_pattern"),
        plugin_pattern=params.get("plugin_pattern"),
    )
    return {"plugins": out, "count": len(out), "plugin_type": plugin_type_arg}


def handle_batch(params: dict[str, Any]) -> dict[str, Any]:
    """Execute a list of operations in one RPC, wrapped in a single undo group.

    params:
      ops: [{op: "<handler_name>", args: {...}}, ...]
      stop_on_error: bool (default False). When False, individual failures
        are recorded in the per-op result but the batch keeps running.
      document_name: optional unique open-document name. The named document is
        made active only for this main-thread dispatch; the prior active
        document is restored in finally. Document lifecycle, arbitrary Python,
        and command handlers are rejected in this mode, and the active document
        is checked before and after every allowed handler.
      undo_group: bool (default True). Set False when the batch itself invokes
        undo or combines read/render/save operations with independently
        undo-wrapped mutations.

    Returns: {"results": [{index, op, result? | error?}, ...]}
    """
    # Imported lazily to avoid a circular import at package load time.
    from . import HANDLERS

    ops = params.get("ops") or []
    stop = bool(params.get("stop_on_error", False))
    use_undo_group = bool(params.get("undo_group", True))
    if not isinstance(ops, list):
        raise ValueError("ops must be a list")

    previous_doc = documents.GetActiveDocument()
    document_name = params.get("document_name")
    scoped = document_name is not None
    doc = previous_doc
    if scoped:
        if not isinstance(document_name, str) or not document_name:
            raise ValueError("document_name must be a non-empty string")
        matches = []
        current = documents.GetFirstDocument()
        while current is not None:
            if (current.GetDocumentName() or "") == document_name:
                matches.append(current)
            current = current.GetNext()
        if not matches:
            raise ValueError(f"no open document named {document_name!r}")
        if len(matches) > 1:
            raise ValueError(
                f"{len(matches)} open documents named {document_name!r}; "
                "document_name must be unique"
            )
        doc = matches[0]

    results: list[dict[str, Any]] = []
    undo_started = False

    def is_open_document(candidate) -> bool:
        current = documents.GetFirstDocument()
        while current is not None:
            if current == candidate:
                return True
            current = current.GetNext()
        return False

    def restore_scoped_target() -> None:
        if doc is not None and is_open_document(doc):
            documents.SetActiveDocument(doc)

    try:
        if scoped and documents.GetActiveDocument() != doc:
            documents.SetActiveDocument(doc)
        # Default behavior remains one outer undo group. Inner handlers may
        # create nested groups, which C4D coalesces into this outer group.
        if use_undo_group and doc is not None:
            doc.StartUndo()
            undo_started = True
        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                results.append({"index": i, "error": f"ops[{i}] must be a dict"})
                if stop:
                    break
                continue
            name = op.get("op")
            args = op.get("args") or {}
            if scoped and name in _SCOPED_BATCH_FORBIDDEN_OPS:
                results.append(
                    {
                        "index": i,
                        "op": name,
                        "error": f"{name!r} is not allowed in a document-scoped batch",
                    }
                )
                break
            if name == "batch":
                results.append({"index": i, "op": name, "error": "nested batch not allowed"})
                if stop:
                    break
                continue
            handler = HANDLERS.get(name)
            if handler is None:
                results.append({"index": i, "op": name, "error": f"unknown op: {name!r}"})
                if stop:
                    break
                continue
            if scoped and documents.GetActiveDocument() != doc:
                restore_scoped_target()
                results.append(
                    {
                        "index": i,
                        "op": name,
                        "error": f"document scope lost before op {name!r}",
                    }
                )
                break
            try:
                r = handler(args)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if scoped and documents.GetActiveDocument() != doc:
                    restore_scoped_target()
                    error += "; handler changed the active document"
                    results.append({"index": i, "op": name, "error": error})
                    break
                results.append({"index": i, "op": name, "error": error})
                if stop:
                    break
            else:
                if scoped and documents.GetActiveDocument() != doc:
                    restore_scoped_target()
                    results.append(
                        {
                            "index": i,
                            "op": name,
                            "error": f"op {name!r} changed the active document",
                        }
                    )
                    break
                results.append({"index": i, "op": name, "result": r})
    finally:
        try:
            if undo_started:
                doc.EndUndo()
        finally:
            if (
                scoped
                and previous_doc is not None
                and is_open_document(previous_doc)
                and documents.GetActiveDocument() != previous_doc
            ):
                documents.SetActiveDocument(previous_doc)
            if scoped:
                c4d.EventAdd()

    return {"results": results, "count": len(results)}
