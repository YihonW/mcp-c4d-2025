"""Redshift AOV listing and atomic list replacement helpers."""

from __future__ import annotations

import math
from typing import Any

import c4d

from ._helpers import document_scope, load_redshift, require_redshift

_AOV_ALIASES = {
    "beauty": "REDSHIFT_AOV_TYPE_BEAUTY",
    "diffuse_lighting": "REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING",
    "reflection": "REDSHIFT_AOV_TYPE_REFLECTION",
    "refraction": "REDSHIFT_AOV_TYPE_REFRACTION",
    "depth": "REDSHIFT_AOV_TYPE_DEPTH",
    "normal": "REDSHIFT_AOV_TYPE_NORMAL",
    "cryptomatte": "REDSHIFT_AOV_TYPE_CRYPTOMATTE",
    "object_id": "REDSHIFT_AOV_TYPE_OBJECT_ID",
}
_AOV_FIELDS = (
    "REDSHIFT_AOV_TYPE",
    "REDSHIFT_AOV_NAME",
    "REDSHIFT_AOV_ENABLED",
    "REDSHIFT_AOV_MULTIPASS_ENABLED",
    "REDSHIFT_AOV_FILE_ENABLED",
    "REDSHIFT_AOV_FILE_PATH",
)


def aov_type_aliases() -> dict[str, int]:
    """Return only aliases backed by the installed Cinema 4D runtime."""
    return {
        alias: int(getattr(c4d, symbol))
        for alias, symbol in _AOV_ALIASES.items()
        if hasattr(c4d, symbol)
    }


def _runtime_symbols() -> dict[str, object]:
    missing = [symbol for symbol in _AOV_FIELDS if not hasattr(c4d, symbol)]
    if missing:
        raise RuntimeError("Redshift AOV symbols unavailable: " + ", ".join(missing))
    return {symbol: getattr(c4d, symbol) for symbol in _AOV_FIELDS}


def _primitive(value: object) -> bool:
    return isinstance(value, (bool, int, float, str)) and not (
        isinstance(value, float) and not math.isfinite(value)
    )


def _safe_aov_params(aov) -> dict[str, bool | int | float | str]:
    known = set(_runtime_symbols().values())
    container = getattr(aov, "GetDataInstance", lambda: None)()
    if container is None:
        return {}
    try:
        pairs = [
            (container.GetIndexId(index), container.GetIndexData(index))
            for index in range(container.GetCount())
        ]
    except Exception:
        return {}
    return {
        str(parameter): value
        for parameter, value in pairs
        if parameter not in known and _primitive(value)
    }


def _aov_record(aov, index: int) -> dict[str, Any]:
    symbols = _runtime_symbols()
    type_value = int(aov.GetParameter(symbols["REDSHIFT_AOV_TYPE"]))
    aliases = {value: alias for alias, value in aov_type_aliases().items()}
    record = {
        "index": index,
        "type": type_value,
        "name": str(aov.GetParameter(symbols["REDSHIFT_AOV_NAME"]) or ""),
        "enabled": bool(aov.GetParameter(symbols["REDSHIFT_AOV_ENABLED"])),
        "multipass_enabled": bool(aov.GetParameter(symbols["REDSHIFT_AOV_MULTIPASS_ENABLED"])),
        "direct_file_enabled": bool(aov.GetParameter(symbols["REDSHIFT_AOV_FILE_ENABLED"])),
        "direct_file_path": str(aov.GetParameter(symbols["REDSHIFT_AOV_FILE_PATH"]) or ""),
        "params": _safe_aov_params(aov),
    }
    if type_value in aliases:
        record["type_alias"] = aliases[type_value]
    return record


def _resolve_render_data(document, name: object):
    if name is None:
        render_data = document.GetActiveRenderData()
        if render_data is None:
            raise ValueError("an active RenderData is required")
        return render_data
    if not isinstance(name, str) or not name.strip():
        raise ValueError("render_data_name must be a non-empty string")

    matches: list[object] = []

    def walk(current) -> None:
        while current is not None:
            if current.GetName() == name:
                matches.append(current)
            child = current.GetDown()
            if child is not None:
                walk(child)
            current = current.GetNext()

    walk(document.GetFirstRenderData())
    if not matches:
        raise ValueError(f"render_data {name!r} not found")
    if len(matches) != 1:
        raise ValueError(f"render_data_name must be unique: {name!r}")
    return matches[0]


def _normalize_type(raw_type: object) -> int:
    aliases = aov_type_aliases()
    if isinstance(raw_type, str):
        alias = raw_type.strip().lower()
        if alias not in aliases:
            raise ValueError(f"unknown AOV type alias: {raw_type!r}")
        return aliases[alias]
    elif isinstance(raw_type, int) and not isinstance(raw_type, bool):
        return raw_type
    raise ValueError("type must be a supported alias or integer")


def _normalize_input(params: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
    type_value = _normalize_type(params.get("type"))

    name = params.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")

    values = {
        key: params[key]
        for key in ("enabled", "multipass_enabled", "direct_file_enabled")
        if key in params
    }
    for key, value in values.items():
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
    if "direct_file_path" in params:
        from .._helpers import _require_writable_path

        values["direct_file_path"] = _require_writable_path(params["direct_file_path"])
    if values.get("direct_file_enabled") is True and "direct_file_path" not in values:
        raise ValueError("direct_file_path is required when direct_file_enabled is true")

    raw_params = params.get("params", {})
    if not isinstance(raw_params, dict):
        raise ValueError("params must be an object")
    normalized_params: dict[int, bool | int | float | str] = {}
    managed_parameters = set(_runtime_symbols().values())
    for key, value in raw_params.items():
        try:
            parameter = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("params keys must be integer parameter ids") from exc
        if isinstance(key, bool) or not _primitive(value):
            raise ValueError("params values must be finite primitive values")
        if parameter in managed_parameters:
            raise ValueError(f"params cannot override managed AOV parameter {parameter}")
        normalized_params[parameter] = value
    values["params"] = normalized_params
    return type_value, name.strip(), values


def _set_parameter(aov, parameter, value) -> None:
    setter = getattr(aov, "SetParameter", None)
    if callable(setter):
        if setter(parameter, value) is False:
            raise RuntimeError(f"failed to set AOV parameter {parameter}")
        return
    aov[parameter] = value


def _exact_clone(aov):
    for method_name in ("GetClone", "Clone"):
        clone = getattr(aov, method_name, None)
        if callable(clone):
            copied = clone()
            if copied is not None and copied is not aov:
                return copied
    return None


def _reconstruct_aov(aov, redshift):
    copied = redshift.RSAOV()
    symbols = _runtime_symbols()
    for parameter in symbols.values():
        _set_parameter(copied, parameter, aov.GetParameter(parameter))
    for parameter, value in _safe_aov_params(aov).items():
        _set_parameter(copied, int(parameter), value)
    return copied


def _clone_aov(aov, redshift):
    copied = _exact_clone(aov)
    return copied if copied is not None else _reconstruct_aov(aov, redshift)


def _rollback_snapshot(original, redshift) -> tuple[list[object] | None, bool]:
    snapshots: list[object] = []
    exact = True
    try:
        for aov in original:
            copied = _exact_clone(aov)
            if copied is None:
                copied = _reconstruct_aov(aov, redshift)
                exact = False
            snapshots.append(copied)
    except Exception:
        return None, False
    return snapshots, exact


def _new_aov(redshift, type_value: int, name: str):
    symbols = _runtime_symbols()
    aov = redshift.RSAOV()
    _set_parameter(aov, symbols["REDSHIFT_AOV_TYPE"], type_value)
    _set_parameter(aov, symbols["REDSHIFT_AOV_NAME"], name)
    return aov


def _apply_values(aov, values: dict[str, Any]) -> None:
    symbols = _runtime_symbols()
    fields = {
        "enabled": "REDSHIFT_AOV_ENABLED",
        "multipass_enabled": "REDSHIFT_AOV_MULTIPASS_ENABLED",
        "direct_file_enabled": "REDSHIFT_AOV_FILE_ENABLED",
        "direct_file_path": "REDSHIFT_AOV_FILE_PATH",
    }
    for key, symbol in fields.items():
        if key in values:
            _set_parameter(aov, symbols[symbol], values[key])
    for parameter, value in values["params"].items():
        _set_parameter(aov, parameter, value)


def _video_post(redshift, render_data):
    video_post = redshift.FindAddVideoPost(render_data, redshift.VPrsrenderer)
    if video_post is None:
        raise RuntimeError("failed to access the Redshift RenderData video post")
    return video_post


def _set_with_rollback(redshift, video_post, original, proposed) -> str:
    try:
        if redshift.RendererSetAOVs(video_post, proposed) is False:
            raise RuntimeError("RendererSetAOVs returned false")
        return "not_needed"
    except Exception as exc:
        restore = getattr(redshift, "RendererSetAOVs", None)
        if not callable(restore):
            rollback = "unavailable"
        else:
            try:
                rollback = "partial" if restore(video_post, original) is False else "succeeded"
            except Exception:
                rollback = "partial"
        raise RuntimeError(f"failed to set Redshift AOVs; rollback={rollback}: {exc}") from exc


def _clear_with_rollback(redshift, video_post, rollback_snapshot, rollback_exact) -> str:
    try:
        if redshift.RendererSetAOVs(video_post, []) is False:
            raise RuntimeError("RendererSetAOVs returned false")
        return "not_needed"
    except Exception as exc:
        if rollback_snapshot is None:
            rollback = "unavailable"
        else:
            try:
                restored = redshift.RendererSetAOVs(video_post, rollback_snapshot)
                rollback = "succeeded" if restored is not False and rollback_exact else "partial"
            except Exception:
                rollback = "partial"
        raise RuntimeError(f"failed to clear Redshift AOVs; rollback={rollback}: {exc}") from exc


def handle_rs_list_aovs(params: dict[str, Any]) -> dict[str, Any]:
    """List the active or named RenderData's Redshift AOV records."""
    require_redshift("aov_api")
    redshift, _ = load_redshift()
    assert redshift is not None
    _runtime_symbols()
    with document_scope(params.get("document_name"), required=True) as document:
        render_data = _resolve_render_data(document, params.get("render_data_name"))
        current = list(redshift.RendererGetAOVs(_video_post(redshift, render_data)))
        return {
            "render_data": {"kind": "render_data", "name": render_data.GetName()},
            "aovs": [_aov_record(aov, index) for index, aov in enumerate(current)],
            "count": len(current),
        }


def handle_rs_upsert_aov(params: dict[str, Any]) -> dict[str, Any]:
    """Create or update one exact type/name AOV through one list replacement."""
    require_redshift("aov_api")
    redshift, _ = load_redshift()
    assert redshift is not None
    _runtime_symbols()
    type_value, name, values = _normalize_input(params)
    with document_scope(params.get("document_name"), required=True) as document:
        render_data = _resolve_render_data(document, params.get("render_data_name"))
        video_post = _video_post(redshift, render_data)
        original = list(redshift.RendererGetAOVs(video_post))
        matches = [
            index
            for index, aov in enumerate(original)
            if int(aov.GetParameter(c4d.REDSHIFT_AOV_TYPE)) == type_value
            and str(aov.GetParameter(c4d.REDSHIFT_AOV_NAME) or "") == name
        ]
        if len(matches) > 1:
            raise ValueError(f"AOV type/name match is ambiguous: {name!r}")

        proposed = [_clone_aov(aov, redshift) for aov in original]
        created = not matches
        if created:
            target = _new_aov(redshift, type_value, name)
            proposed.append(target)
            index = len(proposed) - 1
        else:
            index = matches[0]
            target = proposed[index]
        _apply_values(target, values)
        rollback = _set_with_rollback(redshift, video_post, original, proposed)
        return {
            "render_data": {"kind": "render_data", "name": render_data.GetName()},
            "aov": _aov_record(target, index),
            "created": created,
            "rollback": rollback,
        }


def handle_rs_remove_aov(params: dict[str, Any]) -> dict[str, Any]:
    """Remove one fresh indexed AOV only when its expected identity still matches."""
    index = params.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError("index must be a non-negative integer")
    expected_name = params.get("expected_name")
    if not isinstance(expected_name, str) or not expected_name.strip():
        raise ValueError("expected_name must be a non-empty string")
    expected_type = _normalize_type(params.get("expected_type"))

    require_redshift("aov_api")
    redshift, _ = load_redshift()
    assert redshift is not None
    _runtime_symbols()
    with document_scope(params.get("document_name"), required=True) as document:
        render_data = _resolve_render_data(document, params.get("render_data_name"))
        video_post = _video_post(redshift, render_data)
        original = list(redshift.RendererGetAOVs(video_post))
        if index >= len(original):
            raise ValueError(f"AOV index out of range: {index}")
        removed = _aov_record(original[index], index)
        if removed["name"] != expected_name.strip() or removed["type"] != expected_type:
            raise ValueError(f"stale AOV index {index}: expected name/type no longer match")
        proposed = list(original)
        del proposed[index]
        rollback = _set_with_rollback(redshift, video_post, original, proposed)
        return {
            "render_data": {"kind": "render_data", "name": render_data.GetName()},
            "removed": removed,
            "remaining_count": len(proposed),
            "rollback": rollback,
        }


def handle_rs_clear_aovs(params: dict[str, Any]) -> dict[str, Any]:
    """Clear every AOV only for a named document and an exact force guard."""
    document_name = params.get("document_name")
    if not isinstance(document_name, str) or not document_name.strip():
        raise ValueError("document_name is required to clear all AOVs")
    if params.get("force") is not True:
        raise ValueError("force must be true to clear all AOVs")

    require_redshift("aov_api")
    redshift, _ = load_redshift()
    assert redshift is not None
    _runtime_symbols()
    with document_scope(document_name, required=True) as document:
        render_data = _resolve_render_data(document, params.get("render_data_name"))
        video_post = _video_post(redshift, render_data)
        original = list(redshift.RendererGetAOVs(video_post))
        removed = [_aov_record(aov, index) for index, aov in enumerate(original)]
        rollback_snapshot, rollback_exact = _rollback_snapshot(original, redshift)
        rollback = _clear_with_rollback(redshift, video_post, rollback_snapshot, rollback_exact)
        return {
            "render_data": {"kind": "render_data", "name": render_data.GetName()},
            "removed": removed,
            "remaining_count": 0,
            "rollback": rollback,
        }
