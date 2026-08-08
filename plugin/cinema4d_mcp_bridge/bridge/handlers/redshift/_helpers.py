"""Shared Redshift runtime checks and document safety helpers."""

from __future__ import annotations

import contextlib
import importlib
import os

import c4d
from c4d import documents

from .._helpers import _require_abs_path, _require_writable_path

RS_RENDERER_ID = 1036219
RS_POST_EFFECT_ID = 1040189
RS_NODE_SPACE_ID = "com.redshift3d.redshift4c4d.class.nodespace"

_REQUIRED_AOV_SYMBOLS = (
    "FindAddVideoPost",
    "RendererGetAOVs",
    "RendererSetAOVs",
    "RSAOV",
    "VPrsrenderer",
)
_REQUIRED_MATERIAL_ASSETS = (
    "com.redshift3d.redshift4c4d.node.output",
    "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
)


def load_redshift() -> tuple[object | None, str | None]:
    """Lazily import Redshift without caching a missing runtime."""
    try:
        return importlib.import_module("redshift"), None
    except Exception as exc:
        return None, f"redshift module unavailable: {exc}"


def _open_documents() -> list[object]:
    found: list[object] = []
    document = documents.GetFirstDocument()
    while document is not None:
        found.append(document)
        document = document.GetNext()
    return found


def _is_open_document(target) -> bool:
    return any(document == target for document in _open_documents())


def resolve_document(document_name: str | None, *, required: bool = False):
    if document_name is None:
        target = documents.GetActiveDocument()
        if target is None and required:
            raise ValueError("an active document is required")
        return target
    if not isinstance(document_name, str) or not document_name:
        raise ValueError("document_name must be a non-empty string")
    matches = [
        document for document in _open_documents() if document.GetDocumentName() == document_name
    ]
    if not matches:
        if required:
            raise ValueError(f"document {document_name!r} not found")
        return None
    if len(matches) != 1:
        raise ValueError(f"document_name must be unique: {document_name!r}")
    return matches[0]


def assert_active_document(target) -> None:
    if documents.GetActiveDocument() != target:
        raise RuntimeError("operation changed the active document")


@contextlib.contextmanager
def document_scope(document_name: str | None, *, required: bool = False):
    previous = documents.GetActiveDocument()
    target = resolve_document(document_name, required=required)
    try:
        if target is not previous:
            documents.SetActiveDocument(target)
        assert_active_document(target)
        yield target
        assert_active_document(target)
    finally:
        if (
            previous is not None
            and _is_open_document(previous)
            and documents.GetActiveDocument() != previous
        ):
            documents.SetActiveDocument(previous)
        c4d.EventAdd()


def require_texture_path(value: object) -> str:
    path = _require_abs_path(value, must_exist=True)
    if os.path.isdir(path):
        raise ValueError(f"texture path must be a file, got directory: {path}")
    return path


def require_output_path(value: object, *, overwrite: bool) -> str:
    path = _require_writable_path(value)
    parent = os.path.dirname(path)
    if not os.access(parent, os.W_OK):
        raise ValueError(f"parent directory is not writable: {parent}")
    if os.path.exists(path) and not overwrite:
        raise ValueError(f"output path already exists: {path}")
    return path


def _plugin_feature(plugin_id: int, label: str) -> dict[str, object]:
    try:
        plugin = c4d.plugins.FindPlugin(plugin_id, c4d.PLUGINTYPE_VIDEOPOST)
    except Exception as exc:
        return {"supported": False, "id": plugin_id, "reason": f"{label} probe failed: {exc}"}
    if plugin is None:
        return {"supported": False, "id": plugin_id, "reason": f"{label} plugin is unavailable"}
    return {"supported": True, "id": plugin_id}


def _node_assets() -> tuple[list[object], str | None]:
    try:
        maxon = importlib.import_module("maxon")
        repository = maxon.AssetInterface.GetUserPrefsRepository()
        assets = list(repository.FindAssets(maxon.AssetTypes.NodeTemplate))
        return assets, None
    except Exception as exc:
        return [], f"Redshift node-template repository unavailable: {exc}"


def _asset_id(asset: object) -> str:
    try:
        return str(asset.GetId())
    except Exception:
        return ""


def _feature(supported: bool, reason: str | None = None, **values: object) -> dict[str, object]:
    result: dict[str, object] = {"supported": supported, **values}
    if not supported and reason:
        result["reason"] = reason
    return result


def probe_redshift() -> dict[str, object]:
    """Read one non-mutating snapshot of the Redshift runtime surface."""
    renderer = _plugin_feature(RS_RENDERER_ID, "Redshift renderer")
    post_effect = _plugin_feature(RS_POST_EFFECT_ID, "Redshift post effect")
    redshift, module_reason = load_redshift()
    module = _feature(redshift is not None, module_reason)

    node_assets, node_reason = _node_assets()
    node_space_supported = node_reason is None and bool(node_assets)
    node_space = _feature(
        node_space_supported,
        node_reason or "no Redshift node templates found",
        id=RS_NODE_SPACE_ID,
        node_template_count=len(node_assets),
    )
    asset_ids = {_asset_id(asset) for asset in node_assets}
    missing_assets = [asset for asset in _REQUIRED_MATERIAL_ASSETS if asset not in asset_ids]
    materials = _feature(
        not missing_assets and node_space_supported,
        f"required Redshift material assets unavailable: {', '.join(missing_assets)}"
        if missing_assets
        else node_space.get("reason")
        if not node_space_supported
        else None,
    )

    missing_aov_symbols = [
        symbol
        for symbol in _REQUIRED_AOV_SYMBOLS
        if redshift is None or not hasattr(redshift, symbol)
    ]
    aov_api = _feature(
        not missing_aov_symbols,
        f"Redshift AOV API symbols unavailable: {', '.join(missing_aov_symbols)}",
    )

    light_types: dict[str, object] = {}
    for name in ("area", "dome", "sun", "point", "spot"):
        symbol = f"REDSHIFT_LIGHT_TYPE_{name.upper()}"
        light_types[name] = _feature(
            hasattr(c4d, symbol), f"Cinema 4D symbol unavailable: {symbol}"
        )
    lights = _feature(
        any(feature["supported"] for feature in light_types.values()),
        "no Redshift light type symbols are available",
        types=light_types,
    )

    runtime_ready = bool(renderer["supported"]) and redshift is not None
    camera = _feature(runtime_ready, "Redshift renderer or module is unavailable")
    render = _feature(runtime_ready, "Redshift renderer or module is unavailable")
    return {
        "renderer": renderer,
        "post_effect": post_effect,
        "module": module,
        "node_space": node_space,
        "materials": materials,
        "aov_api": aov_api,
        "lights": lights,
        "camera": camera,
        "render": render,
    }


def require_redshift(*features: str) -> dict[str, object]:
    snapshot = probe_redshift()
    missing: list[str] = []
    for feature in features:
        value = snapshot.get(feature)
        if not isinstance(value, dict):
            raise ValueError(f"unknown Redshift feature: {feature}")
        if not value.get("supported"):
            missing.append(f"{feature}: {value.get('reason', 'unsupported')}")
    if missing:
        raise RuntimeError("Redshift capability unavailable: " + "; ".join(missing))
    return snapshot
