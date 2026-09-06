"""Bounded edits of existing REAL F-Curves, staged off-document before commit."""

from __future__ import annotations

import math
from fractions import Fraction
from itertools import pairwise
from typing import Any

import c4d
from c4d import documents

from ._helpers import _resolve_handle
from .animation import _descid_path, _fps, _integer, _selected_track, _selector_path

_COMMON = {"document_name", "handle", "param_id", "component", "path", "fps"}
_TRANSFORM = {
    "time_scale",
    "time_offset_frames",
    "pivot_frame",
    "value_scale",
    "value_offset",
    "value_pivot",
}
_INTERPOLATION = {
    "linear": "CINTERPOLATION_LINEAR",
    "spline": "CINTERPOLATION_SPLINE",
    "step": "CINTERPOLATION_STEP",
}
_LOOPS = {
    "off": "CLOOP_OFF",
    "constant": "CLOOP_CONSTANT",
    "linear": "CLOOP_CONTINUE",
    "repeat": "CLOOP_REPEAT",
    "offset_repeat": "CLOOP_OFFSETREPEAT",
    "oscillate": "CLOOP_OSCILLATE",
}
# Explicit manual takeover removes options which can override supplied handle offsets.
_MANUAL_INTERFERENCE = (
    "NBIT_CKEY_CLAMP",
    "NBIT_CKEY_AUTOWEIGHT",
    "NBIT_CKEY_REMOVEOVERSHOOT",
    "NBIT_CKEY_LOCK_O",
    "NBIT_CKEY_LOCK_L",
    "NBIT_CKEY_KEEPVISUALANGLE",
)


def _symbol(name: str) -> int:
    value = getattr(c4d, name, None)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError(f"Cinema 4D SDK symbol unavailable: {name}")
    return value


def _methods(obj: Any, *names: str) -> None:
    for name in names:
        if not callable(getattr(obj, name, None)):
            raise RuntimeError(f"Cinema 4D SDK method unavailable: {name}")


def _fields(value: Any, allowed: set[str], name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown {name} fields: {sorted(unknown)}")


def _finite(value: Any, name: str, limit: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number) or (limit is not None and abs(number) > limit):
        raise ValueError(f"{name} is non-finite or outside the supported range")
    return number


def _time(frame: float, fps: int) -> c4d.BaseTime:
    """Use explicit integer fractions; the SDK's seconds constructor rounds to milliseconds."""
    _finite(frame, "frame", 1_000_000)
    rational = (Fraction(str(frame)) / fps).limit_denominator(1_000_000_000)
    try:
        result = c4d.BaseTime(rational.numerator, rational.denominator)
        actual = result.Get() * fps
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("frame cannot be represented by the Cinema 4D time API") from exc
    if (frame != 0 and actual == 0) or not math.isclose(actual, frame, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("frame loses subframe precision in the Cinema 4D time API")
    return result


def _context(params: dict[str, Any], extra_fields: set[str]) -> tuple[Any, Any, Any, Any, int]:
    _fields(params, _COMMON | extra_fields, "request")
    name = params.get("document_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("document_name is required")
    doc = documents.GetActiveDocument()
    if doc is None or doc.GetName() != name:
        raise ValueError(
            "document_name must exactly match the active document; no switching is performed"
        )
    _methods(documents, "GetFirstDocument")
    current, matches = documents.GetFirstDocument(), 0
    while current is not None:
        matches += current.GetName() == name
        current = current.GetNext()
    if matches != 1:
        raise ValueError("document_name is ambiguous or not in the open document list")
    fps = _fps(params, doc)
    did = _selector_path(params)
    handle = params.get("handle")
    if not isinstance(handle, dict):
        raise ValueError("handle is required")
    obj = _resolve_handle(handle)
    _methods(obj, "GetDocument", "GetCTracks", "FindCTrack")
    if obj.GetDocument() != doc:
        raise ValueError("handle must belong to the active document")
    track = _selected_track(obj, params, did)
    if track is None:
        raise ValueError("existing animation track not found")
    _methods(
        track,
        "GetType",
        "GetDescriptionID",
        "GetTrackCategory",
        "GetCurve",
        "IsSynchronized",
        "GetTimeTrack",
        "GetBefore",
        "GetAfter",
        "GetParameter",
    )
    path = _descid_path(track.GetDescriptionID())
    if path[-1][1] != _symbol("DTYPE_REAL") or track.GetTrackCategory() != _symbol(
        "CTRACK_CATEGORY_VALUE"
    ):
        raise ValueError("only existing REAL value tracks are supported")
    if track.GetType() == _symbol("CTtime") or track.GetTimeTrack(doc) is not None:
        raise ValueError("time tracks and tracks using time remapping are unsupported")
    if track.IsSynchronized():
        raise ValueError("synchronized component tracks are unsupported")
    flags = _symbol("DESCFLAGS_GET_0")
    constant_velocity = c4d.DescID(c4d.DescLevel(_symbol("ID_CTRACK_CONSTANTVELOCITY_V"), 0, 0))
    if track.GetParameter(constant_velocity, flags):
        raise ValueError("constant-velocity vector tracks are unsupported")
    if handle.get("kind") == "object":
        _methods(obj, "GetParameter")
        quaternion = c4d.DescID(c4d.DescLevel(_symbol("ID_BASEOBJECT_QUATERNION_ROTATION"), 0, 0))
        if obj.GetParameter(quaternion, flags):
            raise ValueError("quaternion-coupled object tracks are unsupported")
    curve = track.GetCurve(_symbol("CCURVE_CURVE"), False)
    if curve is None:
        raise ValueError("existing F-Curve not found; reading will not create one")
    _methods(curve, "GetKeyCount", "GetKey", "GetTangents")
    count = curve.GetKeyCount()
    if not 0 <= count <= 1000:
        raise ValueError("F-Curve exceeds the 1000-key limit")
    return doc, obj, track, curve, fps


def _keys(curve: Any, fps: int) -> list[dict[str, Any]]:
    _methods(curve, "GetKeyCount", "GetKey", "GetTangents")
    count = curve.GetKeyCount()
    if not 0 <= count <= 1000:
        raise ValueError("F-Curve exceeds the 1000-key limit")
    records = []
    interpolation = {_symbol(symbol): name for name, symbol in _INTERPOLATION.items()}
    auto_bit = _symbol("NBIT_CKEY_AUTO")
    for index in range(count):
        key = curve.GetKey(index)
        _methods(key, "GetTime", "GetValue", "GetInterpolation", "GetNBit")
        # Unlike CKey.GetTime/ValueLeft/Right, these include AUTO and tangent options.
        left_value, right_value, left_time, right_time = curve.GetTangents(index)
        records.append(
            {
                "key_index": index,
                "frame": _finite(key.GetTime().Get() * fps, "key frame"),
                "value": _finite(key.GetValue(), "key value"),
                "interp": interpolation.get(key.GetInterpolation(), str(key.GetInterpolation())),
                "left": {
                    "dt_frames": _finite(left_time * fps, "left time"),
                    "dv": _finite(left_value, "left value"),
                },
                "right": {
                    "dt_frames": _finite(right_time * fps, "right time"),
                    "dv": _finite(right_value, "right value"),
                },
                "tangent_mode": "auto" if key.GetNBit(auto_bit) else "manual",
            }
        )
    return records


def _result(params: dict[str, Any], track: Any, fps: int) -> dict[str, Any]:
    curve = track.GetCurve(_symbol("CCURVE_CURVE"), False)
    keys = _keys(curve, fps)
    loops = {_symbol(symbol): name for name, symbol in _LOOPS.items()}
    return {
        "document_name": params["document_name"],
        "handle": params["handle"],
        "path": _descid_path(track.GetDescriptionID()),
        "fps": fps,
        "key_count": len(keys),
        "keys": keys,
        "before": loops.get(track.GetBefore(), str(track.GetBefore())),
        "after": loops.get(track.GetAfter(), str(track.GetAfter())),
        "samples": [],
    }


def handle_get_fcurve(params: dict[str, Any]) -> dict[str, Any]:
    doc, _obj, track, _curve, fps = _context(params, {"sample_frames"})
    sample_frames = params.get("sample_frames", [])
    if "sample_frames" in params and (
        not isinstance(sample_frames, list) or not 1 <= len(sample_frames) <= 300
    ):
        raise ValueError("sample_frames must contain 1 to 300 frame values")
    times = [_time(_finite(frame, "sample frame", 1_000_000), fps) for frame in sample_frames]
    if times:
        _methods(track, "GetValue")
    result = _result(params, track, fps)
    result["samples"] = [
        {"frame": frame, "value": _finite(track.GetValue(doc, time, fps), "sample value")}
        for frame, time in zip(sample_frames, times, strict=True)
    ]
    return result


def _index(value: Any, count: int) -> int:
    index = _integer(value, "key_index")
    if not 0 <= index < min(count, 1000):
        raise ValueError("key_index is out of range")
    return index


def _side(value: Any, name: str, fps: int) -> dict[str, float]:
    _fields(value, {"dt_frames", "dv"}, name)
    dt = _finite(value.get("dt_frames"), f"{name}.dt_frames", 1_000_000)
    dv = _finite(value.get("dv"), f"{name}.dv")
    if (name == "left" and dt >= 0) or (name == "right" and dt <= 0):
        raise ValueError("left dt_frames must be negative; right dt_frames must be positive")
    _time(dt, fps)
    return {"dt_frames": dt, "dv": dv}


def _set_side(key: Any, curve: Any, side: str, value: dict[str, float], fps: int) -> None:
    suffix = side.title()
    getattr(key, "SetTime" + suffix)(curve, _time(value["dt_frames"], fps))
    getattr(key, "SetValue" + suffix)(curve, value["dv"])


def _tangent_mode(key: Any, mode: str) -> None:
    states = {"NBIT_CKEY_AUTO": mode == "auto"}
    if mode == "manual":
        states.update(dict.fromkeys(_MANUAL_INTERFERENCE, False))
        states["NBIT_CKEY_BREAK"] = True
    for name, enabled in states.items():
        bit = _symbol(name)
        key.ChangeNBit(bit, _symbol("NBITCONTROL_SET" if enabled else "NBITCONTROL_CLEAR"))
        # ChangeNBit returns the new bit state; False is successful for CLEAR.
        if bool(key.GetNBit(bit)) != enabled:
            raise RuntimeError(f"Cinema 4D did not apply tangent flag {name}")


def _staging(track: Any) -> tuple[Any, Any]:
    _methods(track, "GetClone", "CopyTo", "GetObject", "GetPred", "GetNext", "GetLayerObject")
    flags = _symbol("COPYFLAGS_NONE")
    clones = [track.GetClone(flags, None), track.GetClone(flags, None)]
    for clone in clones:
        if clone is None or clone == track:
            raise RuntimeError("reliable native track snapshot unavailable")
        _methods(clone, "CopyTo", "GetDocument", "GetCurve", "GetDescriptionID")
        if clone.GetDocument() is not None or _descid_path(
            clone.GetDescriptionID()
        ) != _descid_path(track.GetDescriptionID()):
            raise RuntimeError("native track clone is not an independent matching snapshot")
        cloned_curve = clone.GetCurve(_symbol("CCURVE_CURVE"), False)
        if cloned_curve is None or cloned_curve == track.GetCurve(_symbol("CCURVE_CURVE"), False):
            raise RuntimeError("native curve snapshot is missing or aliases the original")
    if clones[0] == clones[1] or clones[0].GetCurve(_symbol("CCURVE_CURVE"), False) == clones[
        1
    ].GetCurve(_symbol("CCURVE_CURVE"), False):
        raise RuntimeError("native backup and staging snapshots alias each other")
    return clones[0], clones[1]


def _verify(actual: Any, expected: Any, label: str) -> None:
    """Check requested/read-back fields; no success claim based on a setter return alone."""
    if isinstance(expected, dict):
        for name, value in expected.items():
            _verify(actual[name], value, f"{label}.{name}")
        return
    if isinstance(expected, list) and isinstance(actual, list) and len(actual) == len(expected):
        for index, (item, value) in enumerate(zip(actual, expected, strict=True)):
            _verify(item, value, f"{label}[{index}]")
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(actual, (int, float)) and math.isclose(
            actual, expected, rel_tol=1e-12, abs_tol=1e-9
        ):
            return
    elif actual == expected:
        return
    raise RuntimeError(
        f"F-Curve verification mismatch: {label}; "
        f"expected {repr(expected)[:160]}, got {repr(actual)[:160]}"
    )


def _stable_state(result: dict[str, Any]) -> dict[str, Any]:
    # AUTO effective handles may legitimately recalculate after reattachment to the document.
    return {
        "path": result["path"],
        "before": result["before"],
        "after": result["after"],
        "key_count": result["key_count"],
        "keys": [
            {
                name: value
                for name, value in key.items()
                if key["tangent_mode"] != "auto" or name not in {"left", "right"}
            }
            for key in result["keys"]
        ],
    }


def _commit(
    params: dict[str, Any],
    doc: Any,
    obj: Any,
    track: Any,
    backup: Any,
    staged: Any,
    fps: int,
    indices: list[int],
) -> dict[str, Any]:
    _methods(doc, "StartUndo", "AddUndo", "EndUndo")
    flags = _symbol("COPYFLAGS_NONE")
    undo_type = _symbol("UNDOTYPE_CHANGE")
    original_did = track.GetDescriptionID()
    original_path = _descid_path(original_did)
    expected = _stable_state(_result(params, staged, fps))
    previous = _stable_state(_result(params, backup, fps))
    _verify(_stable_state(_result(params, track, fps)), previous, "native backup")
    topology = (
        track.GetObject(),
        track.GetPred(),
        track.GetNext(),
        track.GetLayerObject(doc),
        obj.GetCTracks(),
    )

    def check_topology() -> None:
        current = (
            track.GetObject(),
            track.GetPred(),
            track.GetNext(),
            track.GetLayerObject(doc),
            obj.GetCTracks(),
        )
        if (
            current != topology
            or _descid_path(track.GetDescriptionID()) != original_path
            or obj.FindCTrack(original_did) != track
        ):
            raise RuntimeError("track ownership, layer or sibling links changed unexpectedly")

    if doc.StartUndo() is False:
        raise RuntimeError("could not start F-Curve undo")
    attempted = False
    try:
        if doc.AddUndo(undo_type, track) is False:
            raise RuntimeError("could not record F-Curve undo; no track write performed")
        attempted = True
        try:
            if not staged.CopyTo(track, flags, None):
                raise RuntimeError("native track CopyTo failed")
            check_topology()
            result = _result(params, track, fps)
            _verify(_stable_state(result), expected, "committed track")
        except Exception as error:
            try:
                if not backup.CopyTo(track, flags, None):
                    raise RuntimeError("native snapshot CopyTo failed")
                check_topology()
                _verify(_stable_state(_result(params, track, fps)), previous, "restored track")
            except Exception as rollback_error:
                raise RuntimeError(
                    f"F-Curve edit failed ({error}); rollback failed ({rollback_error}); "
                    "the result is non-atomic and the track may be partially modified"
                ) from error
            raise RuntimeError(f"F-Curve edit failed; original track restored: {error}") from error
    finally:
        doc.EndUndo()
        if attempted:
            c4d.EventAdd()
    result["input_key_indices"] = indices
    return result


def handle_edit_fcurve_keys(params: dict[str, Any]) -> dict[str, Any]:
    doc, obj, track, curve, fps = _context(params, {"edits"})
    edits = params.get("edits")
    if not isinstance(edits, list) or not 1 <= len(edits) <= 1000:
        raise ValueError("edits must contain 1 to 1000 items")
    records = _keys(curve, fps)
    prepared, seen = [], set()
    for edit in edits:
        _fields(edit, {"key_index", "value", "interp", "tangent_mode", "left", "right"}, "edit")
        index = _index(edit.get("key_index"), len(records))
        if index in seen or len(edit) == 1:
            raise ValueError("edits must have unique key_index values and at least one operation")
        seen.add(index)
        item = dict(edit)
        key = curve.GetKey(index)
        _methods(
            key,
            "SetValue",
            "SetInterpolation",
            "GetNBit",
            "ChangeNBit",
            "SetTimeLeft",
            "SetTimeRight",
            "SetValueLeft",
            "SetValueRight",
        )
        if "value" in item:
            item["value"] = _finite(item["value"], "value")
            if (
                key.GetNBit(_symbol("NBIT_CKEY_LOCK_V"))
                and item["value"] != records[index]["value"]
            ):
                raise ValueError("key value is locked")
        if "interp" in item and (
            not isinstance(item["interp"], str) or item["interp"] not in _INTERPOLATION
        ):
            raise ValueError("interp must be linear/spline/step")
        if "tangent_mode" in item and item["tangent_mode"] not in ("auto", "manual"):
            raise ValueError("tangent_mode must be auto/manual")
        for side in ("left", "right"):
            if side in item:
                if item.get("tangent_mode") != "manual":
                    raise ValueError("explicit tangent handles require tangent_mode=manual")
                item[side] = _side(item[side], side, fps)
            elif item.get("tangent_mode") == "manual":
                # Taking ownership must not expose stale hidden custom handles when AUTO was on.
                item[side] = dict(records[index][side])
                _time(_finite(item[side]["dt_frames"], "tangent time", 1_000_000), fps)
        prepared.append(item)
    backup, staged = _staging(track)
    staged_curve = staged.GetCurve(_symbol("CCURVE_CURVE"), False)
    _methods(staged_curve, "SetKeyDirty")
    for item in prepared:
        key = staged_curve.GetKey(item["key_index"])
        if "value" in item:
            key.SetValue(staged_curve, item["value"])
        if "interp" in item:
            key.SetInterpolation(staged_curve, _symbol(_INTERPOLATION[item["interp"]]))
        if "tangent_mode" in item:
            _tangent_mode(key, item["tangent_mode"])
        for side in ("left", "right"):
            if side in item:
                _set_side(key, staged_curve, side, item[side], fps)
    staged_curve.SetKeyDirty()
    staged_result = _result(params, staged, fps)
    for item in prepared:
        _verify(staged_result["keys"][item["key_index"]], item, "staged edit")
    return _commit(params, doc, obj, track, backup, staged, fps, sorted(seen))


def handle_transform_fcurve(params: dict[str, Any]) -> dict[str, Any]:
    doc, obj, track, curve, fps = _context(params, _TRANSFORM | {"key_indices"})
    if not _TRANSFORM.intersection(params):
        raise ValueError("provide at least one transform field")
    values = {
        name: _finite(
            params.get(name, 1 if name.endswith("scale") else 0),
            name,
            1_000_000 if name in {"time_scale", "time_offset_frames", "pivot_frame"} else None,
        )
        for name in _TRANSFORM
    }
    if values["time_scale"] <= 0:
        raise ValueError("time_scale must be positive; time reversal is unsupported")
    records = _keys(curve, fps)
    indices = params.get("key_indices", list(range(len(records))))
    if not isinstance(indices, list) or not 1 <= len(indices) <= 1000:
        raise ValueError("key_indices must contain 1 to 1000 existing indices")
    selected = [_index(index, len(records)) for index in indices]
    if len(set(selected)) != len(selected):
        raise ValueError("key_indices must be unique")
    if values == {
        "time_scale": 1,
        "time_offset_frames": 0,
        "pivot_frame": values["pivot_frame"],
        "value_scale": 1,
        "value_offset": 0,
        "value_pivot": values["value_pivot"],
    }:
        result = _result(params, track, fps)
        result["input_key_indices"] = []
        return result
    plans = {record["key_index"]: dict(record) for record in records}
    times = [curve.GetKey(index).GetTime() for index in range(len(records))]
    for index in selected:
        key, record, plan = curve.GetKey(index), records[index], plans[index]
        _methods(
            key,
            "GetClone",
            "SetTime",
            "SetValue",
            "SetTimeLeft",
            "SetTimeRight",
            "SetValueLeft",
            "SetValueRight",
        )
        plan["frame"] = _finite(
            values["pivot_frame"]
            + (record["frame"] - values["pivot_frame"]) * values["time_scale"]
            + values["time_offset_frames"],
            "transformed frame",
            1_000_000,
        )
        plan["value"] = _finite(
            values["value_pivot"]
            + (record["value"] - values["value_pivot"]) * values["value_scale"]
            + values["value_offset"],
            "transformed value",
        )
        if key.GetNBit(_symbol("NBIT_CKEY_LOCK_T")) and plan["frame"] != record["frame"]:
            raise ValueError("key time is locked")
        if key.GetNBit(_symbol("NBIT_CKEY_LOCK_V")) and plan["value"] != record["value"]:
            raise ValueError("key value is locked")
        times[index] = _time(plan["frame"], fps)
        if record["tangent_mode"] == "manual":
            if any(key.GetNBit(_symbol(name)) for name in _MANUAL_INTERFERENCE):
                raise ValueError(
                    "manual key has interfering tangent flags; "
                    "explicitly edit tangent_mode=manual first"
                )
            for side in ("left", "right"):
                plan[side] = {
                    "dt_frames": _finite(
                        record[side]["dt_frames"] * values["time_scale"],
                        "transformed tangent time",
                        1_000_000,
                    ),
                    "dv": _finite(
                        record[side]["dv"] * values["value_scale"], "transformed tangent value"
                    ),
                }
                _time(plan[side]["dt_frames"], fps)
    ordered = sorted(range(len(times)), key=lambda index: times[index].Get())
    if any(times[left] == times[right] for left, right in pairwise(ordered)):
        raise ValueError("transformed key times collide, including unselected keys")
    backup, staged = _staging(track)
    staged_curve = staged.GetCurve(_symbol("CCURVE_CURVE"), False)
    _methods(staged_curve, "FlushKeys", "InsertKey", "SetKeyDirty")
    detached = []
    for index in ordered:
        key = staged_curve.GetKey(index).GetClone()
        if key is None:
            raise RuntimeError("native key snapshot unavailable")
        if index in selected:
            plan = plans[index]
            key.SetTime(staged_curve, times[index])
            key.SetValue(staged_curve, plan["value"])
            if plan["tangent_mode"] == "manual":
                for side in ("left", "right"):
                    _set_side(key, staged_curve, side, plan[side], fps)
        detached.append(key)
    staged_curve.FlushKeys(False, False)
    for key in detached:
        if not staged_curve.InsertKey(key, False, False):
            raise RuntimeError("native key insertion failed; original track was not modified")
    staged_curve.SetKeyDirty()
    if staged_curve.GetKeyCount() != len(records):
        raise RuntimeError("staged transform lost keys; original track was not modified")
    staged_result = _result(params, staged, fps)
    for output_index, original_index in enumerate(ordered):
        expected = dict(plans[original_index], key_index=output_index)
        if expected["tangent_mode"] == "auto":
            expected.pop("left")
            expected.pop("right")
        _verify(staged_result["keys"][output_index], expected, "staged transform")
    return _commit(params, doc, obj, track, backup, staged, fps, sorted(selected))


def handle_set_track_extrapolation(params: dict[str, Any]) -> dict[str, Any]:
    doc, obj, track, _curve, fps = _context(params, {"before", "after"})
    if "before" not in params and "after" not in params:
        raise ValueError("before or after is required")
    _methods(track, "SetBefore", "SetAfter")
    modes = {}
    for side in ("before", "after"):
        if side in params:
            mode = params[side]
            if not isinstance(mode, str) or mode not in _LOOPS:
                raise ValueError(f"{side} must be one of {sorted(_LOOPS)}")
            modes[side] = _symbol(_LOOPS[mode])
    backup, staged = _staging(track)
    for side, mode in modes.items():
        getattr(staged, "Set" + side.title())(mode)
    staged_result = _result(params, staged, fps)
    _verify(staged_result, {side: params[side] for side in modes}, "staged extrapolation")
    return _commit(params, doc, obj, track, backup, staged, fps, [])
