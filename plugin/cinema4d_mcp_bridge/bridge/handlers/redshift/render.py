"""Validated Redshift RenderData configuration with rollback."""

from __future__ import annotations

import math
from typing import Any

import c4d
from c4d import documents

from ._helpers import (
    RS_RENDERER_ID,
    document_scope,
    load_redshift,
    require_output_path,
    require_redshift,
)

_FORMAT_SYMBOLS = {
    "png": "FILTER_PNG",
    "jpg": "FILTER_JPG",
    "tif": "FILTER_TIF",
    "exr": "FILTER_EXR",
}


def _symbol(name: str):
    if not hasattr(c4d, name):
        raise RuntimeError(f"Cinema 4D render symbol unavailable: {name}")
    return getattr(c4d, name)


def _primitive(value: object) -> bool:
    return isinstance(value, (bool, int, float, str)) and not (
        isinstance(value, float) and not math.isfinite(value)
    )


def _normalize_input(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")

    values: dict[str, Any] = {"name": name.strip()}
    for key in ("update_if_exists", "make_active"):
        if key in params:
            if not isinstance(params[key], bool):
                raise ValueError(f"{key} must be a boolean")
            values[key] = params[key]

    for key in ("width", "height"):
        if key in params:
            value = params[key]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{key} must be a positive integer")
            values[key] = value

    if "frame" in params:
        frame = params["frame"]
        if not isinstance(frame, int) or isinstance(frame, bool):
            raise ValueError("frame must be an integer")
        values["frame"] = frame

    if "output_format" in params:
        output_format = params["output_format"]
        if not isinstance(output_format, str) or output_format not in _FORMAT_SYMBOLS:
            raise ValueError("output_format must be png, jpg, tif, or exr")
        values["output_format"] = output_format

    for key in ("beauty_path", "multipass_path"):
        if key in params:
            values[key] = require_output_path(params[key], overwrite=True)

    raw_params = params.get("redshift_params", {})
    if not isinstance(raw_params, dict):
        raise ValueError("redshift_params must be an object")
    normalized_params: dict[int, bool | int | float | str] = {}
    for key, value in raw_params.items():
        try:
            parameter = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("redshift_params keys must be integer parameter ids") from exc
        if isinstance(key, bool) or not _primitive(value):
            raise ValueError("redshift_params values must be finite primitive values")
        normalized_params[parameter] = value
    values["redshift_params"] = normalized_params
    return values


def _render_data_matches(document, name: str) -> list[object]:
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
    return matches


def _render_settings(document, values: dict[str, Any]) -> dict[object, object]:
    settings: dict[object, object] = {
        _symbol("RDATA_RENDERENGINE"): RS_RENDERER_ID,
    }
    if "width" in values:
        settings[_symbol("RDATA_XRES")] = float(values["width"])
    if "height" in values:
        settings[_symbol("RDATA_YRES")] = float(values["height"])
    if "frame" in values:
        base_time = getattr(c4d, "BaseTime", None)
        if not callable(base_time):
            raise RuntimeError("Cinema 4D render symbol unavailable: BaseTime")
        frame_time = base_time(values["frame"], document.GetFps())
        settings[_symbol("RDATA_FRAMESEQUENCE")] = _symbol("RDATA_FRAMESEQUENCE_CURRENTFRAME")
        settings[_symbol("RDATA_FRAMEFROM")] = frame_time
        settings[_symbol("RDATA_FRAMETO")] = frame_time
    if "output_format" in values:
        filter_id = _symbol(_FORMAT_SYMBOLS[values["output_format"]])
        settings[_symbol("RDATA_FORMAT")] = filter_id
        settings[_symbol("RDATA_MULTIPASS_SAVEFORMAT")] = filter_id
    if "beauty_path" in values:
        settings[_symbol("RDATA_PATH")] = values["beauty_path"]
    if "multipass_path" in values:
        settings[_symbol("RDATA_MULTIPASS_FILENAME")] = values["multipass_path"]
    return settings


def _set_video_post_parameter(video_post, parameter: int, value: object) -> None:
    setter = getattr(video_post, "SetParameter", None)
    if callable(setter):
        if setter(parameter, value) is False:
            raise RuntimeError(f"failed to set Redshift parameter {parameter}")
        return
    video_post[parameter] = value


def _clone_render_data(render_data):
    clone = getattr(render_data, "GetClone", None)
    if not callable(clone):
        return None
    copied = clone()
    return copied if copied is not render_data else None


def _restore_existing(snapshot, target) -> str:
    if snapshot is None:
        return "unavailable"
    copy_to = getattr(snapshot, "CopyTo", None)
    if not callable(copy_to):
        return "unavailable"
    try:
        result = copy_to(target, _symbol("COPYFLAGS_0"), None)
        return "succeeded" if result is not False else "partial"
    except Exception:
        return "partial"


def handle_rs_configure_render(params: dict[str, Any]) -> dict[str, Any]:
    """Create or update one exact Redshift RenderData without implicit activation."""
    values = _normalize_input(params)
    require_redshift("render")
    redshift, reason = load_redshift()
    if redshift is None:
        raise RuntimeError(reason or "redshift module unavailable")
    find_video_post = getattr(redshift, "FindAddVideoPost", None)
    if not callable(find_video_post):
        raise RuntimeError("Redshift symbol unavailable: FindAddVideoPost")
    renderer_symbol = getattr(redshift, "VPrsrenderer", None)
    if renderer_symbol is None or int(renderer_symbol) != RS_RENDERER_ID:
        raise RuntimeError("Redshift symbol unavailable or unexpected: VPrsrenderer")

    with document_scope(params.get("document_name"), required=True) as document:
        settings = _render_settings(document, values)
        matches = _render_data_matches(document, values["name"])
        update_if_exists = values.get("update_if_exists", False)
        if matches and not update_if_exists:
            raise ValueError(f"render_data already exists: {values['name']!r}")
        if len(matches) > 1:
            raise ValueError(f"render_data name is ambiguous: {values['name']!r}")

        created = not matches
        if created:
            constructor = getattr(documents, "RenderData", None)
            if not callable(constructor):
                raise RuntimeError("Cinema 4D render symbol unavailable: RenderData")
            render_data = constructor()
            if render_data is None:
                raise RuntimeError("failed to allocate RenderData")
            render_data.SetName(values["name"])
            snapshot = None
        else:
            render_data = matches[0]
            snapshot = _clone_render_data(render_data)

        inserted = False
        try:
            if created:
                document.InsertRenderData(render_data)
                inserted = True
            for parameter, value in settings.items():
                render_data[parameter] = value
            video_post = find_video_post(render_data, renderer_symbol)
            if video_post is None:
                raise RuntimeError("failed to create or access the Redshift video post")
            for parameter, value in values["redshift_params"].items():
                _set_video_post_parameter(video_post, parameter, value)
            if values.get("make_active", False):
                document.SetActiveRenderData(render_data)
        except Exception as exc:
            if created and inserted:
                try:
                    render_data.Remove()
                    rollback = "succeeded"
                except Exception:
                    rollback = "partial"
            else:
                rollback = _restore_existing(snapshot, render_data)
            raise RuntimeError(
                f"failed to configure Redshift RenderData; rollback={rollback}: {exc}"
            ) from exc

        return {
            "document_name": document.GetDocumentName(),
            "handle": {"kind": "render_data", "name": render_data.GetName()},
            "created": created,
            "active": document.GetActiveRenderData() == render_data,
            "renderer_id": RS_RENDERER_ID,
            "video_post_id": RS_RENDERER_ID,
            "rollback": "not_needed",
        }
