"""Create and update native Redshift camera objects without camera fallbacks."""

from __future__ import annotations

import math

import c4d

from ._helpers import document_scope, require_redshift
from .lights import _objects_named, _start_undo

CAMERA_PARAMETER_SYMBOLS = {
    "exposure": "RSCAMERAOBJECT_EXPOSURE",
    "shutter_time": "RSCAMERAOBJECT_SHUTTER_TIME_RATIO",
    "shutter_angle": "RSCAMERAOBJECT_SHUTTER_ANGLE",
    "focus_distance": "RSCAMERAOBJECT_FOCUS_DISTANCE",
    "f_stop": "RSCAMERAOBJECT_FNUMBER_VALUE",
    "depth_of_field": "RSCAMERAOBJECT_BOKEH_ENABLED",
}


def _finite(value: object, setting: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{setting} must be a finite number")
    return float(value)


def _triple(value: object, setting: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{setting} must be a three-value tuple")
    return tuple(_finite(component, setting) for component in value)


def _validate_input(params: dict[str, object]) -> tuple[str, bool, dict[str, object]]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    update_if_exists = params.get("update_if_exists", False)
    if not isinstance(update_if_exists, bool):
        raise ValueError("update_if_exists must be a boolean")

    values: dict[str, object] = {}
    for setting in ("position", "rotation"):
        if setting in params:
            values[setting] = _triple(params[setting], setting)
    for setting in ("exposure", "shutter_angle"):
        if setting in params:
            values[setting] = _finite(params[setting], setting)
    for setting in ("shutter_time", "focus_distance", "f_stop"):
        if setting in params:
            number = _finite(params[setting], setting)
            if number <= 0:
                raise ValueError(f"{setting} must be positive")
            values[setting] = number
    if "depth_of_field" in params:
        if not isinstance(params["depth_of_field"], bool):
            raise ValueError("depth_of_field must be a boolean")
        values["depth_of_field"] = params["depth_of_field"]
    return name, update_if_exists, values


def _camera_parameter_ids(
    values: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, str]]]:
    available: dict[str, object] = {}
    unavailable: list[dict[str, str]] = []
    for setting, symbol in CAMERA_PARAMETER_SYMBOLS.items():
        if setting not in values:
            continue
        value = getattr(c4d, symbol, None)
        if value is None:
            unavailable.append(
                {"setting": setting, "reason": f"Cinema 4D symbol unavailable: {symbol}"}
            )
        else:
            available[setting] = value
    return available, unavailable


def handle_rs_set_camera(params: dict[str, object]) -> dict[str, object]:
    """Create a native ``Orscamera`` or update one exact existing native camera."""
    from .._helpers import _object_path

    name, update_if_exists, values = _validate_input(params)
    require_redshift("camera")
    camera_type = getattr(c4d, "Orscamera", None)
    if camera_type is None:
        raise RuntimeError("camera unsupported: Cinema 4D symbol unavailable: Orscamera")
    parameter_ids, unavailable = _camera_parameter_ids(values)

    with document_scope(params.get("document_name"), required=True) as document:
        matches = _objects_named(document, name)
        if len(matches) > 1:
            raise ValueError(f"object name is ambiguous: {name!r}")
        if matches and not update_if_exists:
            raise ValueError(f"object already exists: {name!r}")

        created = not matches
        if created:
            obj = c4d.BaseObject(camera_type)
            if obj is None:
                raise RuntimeError("failed to create native Redshift camera")
            obj.SetName(name)
        else:
            obj = matches[0]
            if obj.GetType() != camera_type:
                raise ValueError(f"object is not a Redshift camera: {name!r}")

        undo_type = getattr(c4d, "UNDOTYPE_NEW" if created else "UNDOTYPE_CHANGE", None)
        undo_supported, end_undo = _start_undo(
            document,
            undo_type,
            obj,
            insert=(lambda: document.InsertObject(obj)) if created else None,
        )
        try:
            applied: list[str] = []
            if "position" in values:
                obj.SetRelPos(c4d.Vector(*values["position"]))
                applied.append("position")
            if "rotation" in values:
                obj.SetRelRot(c4d.Vector(*values["rotation"]))
                applied.append("rotation")
            for setting in CAMERA_PARAMETER_SYMBOLS:
                if setting in parameter_ids:
                    obj[parameter_ids[setting]] = values[setting]
                    applied.append(setting)
        finally:
            if end_undo is not None:
                end_undo()

        return {
            "document_name": document.GetDocumentName(),
            "handle": {"kind": "object", "path": _object_path(obj), "name": obj.GetName()},
            "created": created,
            "applied": applied,
            "unavailable": unavailable,
            "undo_supported": undo_supported,
        }
