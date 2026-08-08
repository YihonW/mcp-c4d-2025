"""Create and update native Redshift light objects without renderer fallbacks."""

from __future__ import annotations

import math

import c4d

from ._helpers import document_scope, require_redshift, require_texture_path

LIGHT_TYPE_SYMBOLS = {
    "area": "REDSHIFT_LIGHT_TYPE_AREA",
    "dome": "REDSHIFT_LIGHT_TYPE_DOME",
    "sun": "REDSHIFT_LIGHT_TYPE_SUN",
    "point": "REDSHIFT_LIGHT_TYPE_POINT",
    "spot": "REDSHIFT_LIGHT_TYPE_SPOT",
}

_LIGHT_PARAMETER_SYMBOLS = {
    "color": "REDSHIFT_LIGHT_COLOR",
    "intensity": "REDSHIFT_LIGHT_INTENSITY",
    "exposure": "REDSHIFT_LIGHT_EXPOSURE",
}


def _finite(value: object, setting: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{setting} must be a finite number")
    return float(value)


def _triple(
    value: object, setting: str, *, unit_interval: bool = False
) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{setting} must be a three-value tuple")
    result = tuple(_finite(component, setting) for component in value)
    if unit_interval and any(component < 0 or component > 1 for component in result):
        raise ValueError(f"{setting} components must be in 0..1")
    return result


def _objects_named(document, name: str) -> list[object]:
    matches: list[object] = []

    def walk(obj) -> None:
        while obj is not None:
            if obj.GetName() == name:
                matches.append(obj)
            child = obj.GetDown()
            if child is not None:
                walk(child)
            obj = obj.GetNext()

    walk(document.GetFirstObject())
    return matches


def _runtime_symbol(name: str, *, setting: str) -> object:
    value = getattr(c4d, name, None)
    if value is None:
        raise RuntimeError(f"{setting} unsupported: Cinema 4D symbol unavailable: {name}")
    return value


def _validate_input(params: dict[str, object]) -> tuple[str, str, bool, dict[str, object]]:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    light_type = params.get("type")
    if light_type not in LIGHT_TYPE_SYMBOLS:
        raise ValueError(f"type must be one of: {', '.join(LIGHT_TYPE_SYMBOLS)}")
    update_if_exists = params.get("update_if_exists", False)
    if not isinstance(update_if_exists, bool):
        raise ValueError("update_if_exists must be a boolean")

    values: dict[str, object] = {}
    if "position" in params:
        values["position"] = _triple(params["position"], "position")
    if "rotation" in params:
        values["rotation"] = _triple(params["rotation"], "rotation")
    if "color" in params:
        values["color"] = _triple(params["color"], "color", unit_interval=True)
    for setting in ("intensity", "exposure"):
        if setting in params:
            number = _finite(params[setting], setting)
            if setting == "intensity" and number <= 0:
                raise ValueError("intensity must be positive")
            values[setting] = number
    if "dome_texture" in params:
        if light_type != "dome":
            raise ValueError("dome_texture is supported only for dome lights")
        values["dome_texture"] = require_texture_path(params["dome_texture"])
    return name, light_type, update_if_exists, values


def _preflight(
    light_type: str, values: dict[str, object]
) -> tuple[object, object, dict[str, object], object | None]:
    type_value = _runtime_symbol(LIGHT_TYPE_SYMBOLS[light_type], setting=light_type)
    type_parameter_id = _runtime_symbol("REDSHIFT_LIGHT_TYPE", setting="type")
    parameter_ids = {
        setting: _runtime_symbol(symbol, setting=setting)
        for setting, symbol in _LIGHT_PARAMETER_SYMBOLS.items()
        if setting in values
    }
    texture_descid = None
    if "dome_texture" in values:
        dome_id = _runtime_symbol("REDSHIFT_LIGHT_DOME_TEX0", setting="dome_texture")
        file_path_id = _runtime_symbol("REDSHIFT_FILE_PATH", setting="dome_texture")
        container_type = _runtime_symbol("DTYPE_BASECONTAINER", setting="dome_texture")
        filename_type = _runtime_symbol("DTYPE_FILENAME", setting="dome_texture")
        light_type_id = _runtime_symbol("Orslight", setting="dome_texture")
        texture_descid = c4d.DescID(
            c4d.DescLevel(dome_id, container_type, light_type_id),
            c4d.DescLevel(file_path_id, filename_type, light_type_id),
        )
    return type_value, type_parameter_id, parameter_ids, texture_descid


def _start_undo(document, undo_type, obj, *, insert=None) -> tuple[bool, object | None]:
    start = getattr(document, "StartUndo", None)
    add = getattr(document, "AddUndo", None)
    end = getattr(document, "EndUndo", None)
    if undo_type is None or not all(callable(method) for method in (start, add, end)):
        if insert is not None:
            insert()
        return False, None
    try:
        if start() is False:
            if insert is not None:
                insert()
            return False, None
    except Exception:
        if insert is not None:
            insert()
        return False, None
    try:
        if insert is not None:
            insert()
        add(undo_type, obj)
    except Exception:
        try:
            end()
        finally:
            raise
    return True, end


def _apply_light(
    obj,
    type_value,
    type_parameter_id,
    parameter_ids: dict[str, object],
    texture_descid,
    values: dict[str, object],
) -> list[str]:
    obj[type_parameter_id] = type_value
    applied: list[str] = []
    if "position" in values:
        obj.SetRelPos(c4d.Vector(*values["position"]))
        applied.append("position")
    if "rotation" in values:
        obj.SetRelRot(c4d.Vector(*values["rotation"]))
        applied.append("rotation")
    for setting in ("color", "intensity", "exposure"):
        if setting in values:
            value = values[setting]
            obj[parameter_ids[setting]] = c4d.Vector(*value) if setting == "color" else value
            applied.append(setting)
    if "dome_texture" in values:
        obj[texture_descid] = values["dome_texture"]
        applied.append("dome_texture")
    return applied


def handle_rs_create_light(params: dict[str, object]) -> dict[str, object]:
    """Create a native ``Orslight`` or update one exact existing native object."""
    from .._helpers import _object_path

    name, light_type, update_if_exists, values = _validate_input(params)
    require_redshift("lights")
    type_value, type_parameter_id, parameter_ids, texture_descid = _preflight(light_type, values)
    light_object_type = _runtime_symbol("Orslight", setting="light")
    with document_scope(params.get("document_name"), required=True) as document:
        matches = _objects_named(document, name)
        if len(matches) > 1:
            raise ValueError(f"object name is ambiguous: {name!r}")
        if matches and not update_if_exists:
            raise ValueError(f"object already exists: {name!r}")

        created = not matches
        if created:
            obj = c4d.BaseObject(light_object_type)
            if obj is None:
                raise RuntimeError("failed to create native Redshift light")
            obj.SetName(name)
        else:
            obj = matches[0]
            if obj.GetType() != light_object_type:
                raise ValueError(f"object is not a Redshift light: {name!r}")

        undo_type = getattr(c4d, "UNDOTYPE_NEW" if created else "UNDOTYPE_CHANGE", None)
        undo_supported, end_undo = _start_undo(
            document,
            undo_type,
            obj,
            insert=(lambda: document.InsertObject(obj)) if created else None,
        )
        try:
            applied = _apply_light(
                obj,
                type_value,
                type_parameter_id,
                parameter_ids,
                texture_descid,
                values,
            )
        finally:
            if end_undo is not None:
                end_undo()

        return {
            "document_name": document.GetDocumentName(),
            "handle": {
                "kind": "object",
                "path": _object_path(obj),
                "name": obj.GetName(),
            },
            "type": light_type,
            "created": created,
            "applied": applied,
            "undo_supported": undo_supported,
        }
