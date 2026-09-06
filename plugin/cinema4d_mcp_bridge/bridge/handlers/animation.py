"""Animation handlers: list_tracks, get_keyframes, set_keyframe, delete_keyframe, delete_track.

Track operations accept complete ``path`` DescIDs as [[id, dtype, creator], ...]
or the legacy ``param_id`` / ``component`` selector. Full paths also address
user-data scalar channels and individual user-data vector components.
"""

from __future__ import annotations

import contextlib
import math
from typing import Any

import c4d
from c4d import documents

from ._helpers import _param_dtype, _resolve_handle

_DTYPE_NAMES: dict[int, str] = {
    c4d.DTYPE_REAL: "real",
    c4d.DTYPE_LONG: "long",
    c4d.DTYPE_BOOL: "bool",
    c4d.DTYPE_VECTOR: "vector",
}

_INTERP_NAMES: dict[int, str] = {
    c4d.CINTERPOLATION_LINEAR: "linear",
    c4d.CINTERPOLATION_SPLINE: "spline",
    c4d.CINTERPOLATION_STEP: "step",
}

_COMPONENT_FROM_VECTOR_ID = {
    c4d.VECTOR_X: "x",
    c4d.VECTOR_Y: "y",
    c4d.VECTOR_Z: "z",
}


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not -(2**31) <= value < 2**31:
        raise ValueError(f"{name} must be a signed 32-bit integer")
    return value


def _selector_path(params: dict[str, Any]) -> c4d.DescID | None:
    """Validate either a complete DescID or the legacy selector before any write."""
    has_path = "path" in params
    if has_path == (params.get("param_id") is not None):
        raise ValueError("provide exactly one of path or param_id")
    component = params.get("component")
    if has_path:
        if component is not None or params.get("dtype") is not None:
            raise ValueError("path cannot be combined with component or dtype")
        path = params["path"]
        if not isinstance(path, (list, tuple)) or not 1 <= len(path) <= 3:
            raise ValueError("path must contain one to three [id, dtype, creator] levels")
        levels = []
        for level in path:
            if not isinstance(level, (list, tuple)) or len(level) != 3:
                raise ValueError("each path level must be [id, dtype, creator]")
            levels.append(c4d.DescLevel(*(_integer(value, "path level") for value in level)))
        return c4d.DescID(*levels)
    _integer(params["param_id"], "param_id")
    if component is not None and component not in ("x", "y", "z"):
        raise ValueError("component must be x/y/z or null")
    return None


def _descid_path(did: c4d.DescID) -> list[list[int]]:
    return [[int(did[i].id), int(did[i].dtype), int(did[i].creator)] for i in range(did.GetDepth())]


def _frame_range(params: dict[str, Any]) -> tuple[int | None, int | None]:
    start, end = params.get("start_frame"), params.get("end_frame")
    for name, value in (("start_frame", start), ("end_frame", end)):
        if value is not None:
            _integer(value, name)
    if start is not None and end is not None and start > end:
        raise ValueError("end_frame must be >= start_frame")
    return start, end


def _fps(params: dict[str, Any], doc: Any) -> int:
    value = _integer(params.get("fps", doc.GetFps() if doc else 30), "fps")
    if value <= 0:
        raise ValueError("fps must be positive")
    return value


def _describe_track(track: c4d.CTrack) -> dict[str, Any]:
    did = track.GetDescriptionID()
    top = did[0]
    entry: dict[str, Any] = {
        "name": track.GetName(),
        "param_id": int(top.id),
        "dtype": _DTYPE_NAMES.get(int(top.dtype), str(int(top.dtype))),
        "component": None,
        "path": _descid_path(did),
    }
    depth = did.GetDepth()
    # A user-data slot is not itself a vector component. Its actual parent
    # must be VECTOR, including the second level of a user-data vector.
    if depth > 1 and int(did[depth - 2].dtype) == c4d.DTYPE_VECTOR:
        entry["component"] = _COMPONENT_FROM_VECTOR_ID.get(int(did[depth - 1].id))

    curve = track.GetCurve()
    entry["key_count"] = curve.GetKeyCount() if curve is not None else 0
    return entry


def handle_list_tracks(params: dict[str, Any]) -> dict[str, Any]:
    """Enumerate CTracks on the resolved entity.

    params:
      handle: target (BaseList2D that supports GetCTracks)
    """
    h = params.get("handle")
    if not h:
        raise ValueError("handle required")
    obj = _resolve_handle(h)
    if obj is None:
        raise ValueError(f"handle not resolved: {h}")
    if not hasattr(obj, "GetCTracks"):
        raise ValueError(f"handle {h!r} has no animation tracks (GetCTracks unavailable)")

    tracks = obj.GetCTracks() or []
    out = [_describe_track(t) for t in tracks]
    return {"tracks": out, "count": len(out)}


def _find_track(obj: c4d.BaseList2D, param_id: int, component: str | None) -> c4d.CTrack | None:
    """Locate the CTrack for (param_id, component) on an animated object."""
    tracks = obj.GetCTracks() or []
    vec_id = None
    if component is not None:
        vec_map = {"x": c4d.VECTOR_X, "y": c4d.VECTOR_Y, "z": c4d.VECTOR_Z}
        if component not in vec_map:
            raise ValueError(f"component must be x/y/z or null, got {component!r}")
        vec_id = vec_map[component]
    for t in tracks:
        did = t.GetDescriptionID()
        top = did[0]
        if int(top.id) != int(param_id):
            continue
        try:
            depth = did.GetDepth()
        except Exception:
            depth = 1
        if vec_id is None:
            if depth == 1:
                return t
        else:
            if depth == 2 and int(top.dtype) == c4d.DTYPE_VECTOR:
                with contextlib.suppress(Exception):
                    if int(did[1].id) == int(vec_id):
                        return t
    return None


def _selected_track(
    obj: c4d.BaseList2D, params: dict[str, Any], did: c4d.DescID | None
) -> c4d.CTrack | None:
    if did is not None:
        return obj.FindCTrack(did)
    return _find_track(obj, params["param_id"], params.get("component"))


def handle_get_keyframes(params: dict[str, Any]) -> dict[str, Any]:
    """Read keys from a specific CTrack.

    params:
      handle:       target
      param_id:     top-level description id
      component:    "x"/"y"/"z"/null
      start_frame:  inclusive lower bound (optional)
      end_frame:    inclusive upper bound (optional)
      fps:          override for BaseTime conversion (default: doc fps)
    """
    h = params.get("handle")
    if not h:
        raise ValueError("handle required")
    did = _selector_path(params)
    start_frame, end_frame = _frame_range(params)
    doc = documents.GetActiveDocument()
    fps = _fps(params, doc)
    obj = _resolve_handle(h)
    if obj is None:
        raise ValueError(f"handle not resolved: {h}")
    if not hasattr(obj, "GetCTracks"):
        raise ValueError(f"handle {h!r} has no animation tracks")

    track = _selected_track(obj, params, did)
    if track is None:
        return {"keys": [], "track": None, "count": 0}

    curve = track.GetCurve()
    if curve is None:
        return {"keys": [], "track": _describe_track(track), "count": 0}

    keys: list[dict[str, Any]] = []
    for i in range(curve.GetKeyCount()):
        k = curve.GetKey(i)
        time = k.GetTime()
        frame = float(time.Get()) * fps
        if start_frame is not None and time < c4d.BaseTime(start_frame, fps):
            continue
        if end_frame is not None and c4d.BaseTime(end_frame, fps) < time:
            continue
        interp_id = None
        with contextlib.suppress(Exception):
            interp_id = int(k.GetInterpolation())
        keys.append(
            {
                "frame": frame,
                "value": k.GetGeData()
                if track.GetTrackCategory() == c4d.CTRACK_CATEGORY_DATA
                else float(k.GetValue()),
                "interp": _INTERP_NAMES.get(interp_id, str(interp_id)),
            }
        )

    return {
        "track": _describe_track(track),
        "keys": keys,
        "count": len(keys),
    }


def handle_delete_keyframe(params: dict[str, Any]) -> dict[str, Any]:
    """Delete keys on a CTrack.

    params:
      handle:       target
      param_id:     top-level id
      component:    "x"/"y"/"z"/null
      frame:        single frame to delete (exclusive with start/end)
      start_frame, end_frame: inclusive range to delete
      fps:          override for BaseTime → frame conversion
    """
    h = params.get("handle")
    if not h:
        raise ValueError("handle required")
    did = _selector_path(params)
    start_frame, end_frame = _frame_range(params)
    frame = params.get("frame")
    if frame is not None:
        _integer(frame, "frame")
        if start_frame is not None or end_frame is not None:
            raise ValueError("frame is exclusive with start_frame / end_frame")
    doc = documents.GetActiveDocument()
    fps = _fps(params, doc)
    obj = _resolve_handle(h)
    if obj is None:
        raise ValueError(f"handle not resolved: {h}")
    if not hasattr(obj, "GetCTracks"):
        raise ValueError(f"handle {h!r} has no animation tracks")

    track = _selected_track(obj, params, did)
    if track is None:
        return {"removed": 0, "track": None}
    curve = track.GetCurve()
    if curve is None:
        return {"removed": 0, "track": _describe_track(track)}

    if doc is not None:
        doc.StartUndo()
        with contextlib.suppress(Exception):
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, track)

    removed = 0
    try:
        # Walk keys in reverse so index-based DelKey stays valid mid-iteration.
        for i in range(curve.GetKeyCount() - 1, -1, -1):
            k = curve.GetKey(i)
            time = k.GetTime()
            if frame is not None:
                if time != c4d.BaseTime(frame, fps):
                    continue
            else:
                if start_frame is not None and time < c4d.BaseTime(start_frame, fps):
                    continue
                if end_frame is not None and c4d.BaseTime(end_frame, fps) < time:
                    continue
            curve.DelKey(i)
            removed += 1
    finally:
        if doc is not None:
            doc.EndUndo()
    c4d.EventAdd()

    return {
        "removed": removed,
        "track": _describe_track(track),
    }


# ---------------------------------------------------------------------------
# Keyframe writes
# ---------------------------------------------------------------------------


def _pick_keyframe_dtype(declared: int | None, component: str | None) -> int:
    """Pick the DescID dtype for a keyframe based on description and component."""
    if component is not None:
        return c4d.DTYPE_VECTOR
    if declared is None:
        return c4d.DTYPE_REAL
    if declared in (c4d.DTYPE_LONG, c4d.DTYPE_BOOL, c4d.DTYPE_REAL, c4d.DTYPE_VECTOR):
        return declared
    return c4d.DTYPE_REAL


def handle_set_keyframe(params: dict[str, Any]) -> dict[str, Any]:
    """Add or update a keyframe on the resolved entity's parameter.

    Supports scalar (REAL/LONG/BOOL) and vector (x/y/z) parameters. The dtype
    is inferred from the object's description; pass ``dtype`` explicitly to
    override (e.g. ``"long"`` for enum-backed params).

    params:
      handle:    target
      param_id:  top-level description id (int)
      component: "x" | "y" | "z" | null   (sub-component for vector params)
      frame:     frame number (int)
      value:     new value (number or bool)
      fps:       optional override for time base (default: doc fps)
      interp:    "linear" | "spline" | "step"  (default "spline")
      dtype:     optional override: "real" | "long" | "bool" | "vector"
    """
    h = params.get("handle")
    pid = params.get("param_id")
    comp = params.get("component")
    frame = params.get("frame")
    value = params.get("value")
    interp_name = params.get("interp", "spline")
    dtype_name = params.get("dtype")

    if not h:
        raise ValueError("handle required")
    did = _selector_path(params)
    _integer(frame, "frame")
    try:
        finite_value = isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite_value = False
    if not finite_value:
        raise ValueError("value must be a finite number or bool")

    obj = _resolve_handle(h)
    if obj is None:
        raise ValueError(f"handle not resolved: {h}")

    doc = documents.GetActiveDocument()
    if doc is None:
        raise ValueError("no active document")
    fps = _fps(params, doc)

    # Resolve the parameter dtype from description unless overridden.
    dtype_overrides = {
        "real": c4d.DTYPE_REAL,
        "long": c4d.DTYPE_LONG,
        "bool": c4d.DTYPE_BOOL,
        "vector": c4d.DTYPE_VECTOR,
    }
    if did is not None:
        declared = int(did[did.GetDepth() - 1].dtype)
        if declared not in (c4d.DTYPE_REAL, c4d.DTYPE_LONG, c4d.DTYPE_BOOL):
            raise ValueError(
                "path must end in a REAL/LONG/BOOL scalar channel; "
                "append a REAL component for vectors"
            )
    elif dtype_name is not None:
        if dtype_name not in dtype_overrides:
            raise ValueError(f"dtype must be one of {sorted(dtype_overrides)}, got {dtype_name!r}")
        declared = dtype_overrides[dtype_name]
    else:
        declared = _param_dtype(obj, int(pid))

    effective_dtype = _pick_keyframe_dtype(declared, comp)

    if did is None:
        if comp is None:
            if effective_dtype == c4d.DTYPE_VECTOR:
                raise ValueError("vector keyframes require component x/y/z")
            did = c4d.DescID(c4d.DescLevel(int(pid), effective_dtype, 0))
        else:
            cm = {"x": c4d.VECTOR_X, "y": c4d.VECTOR_Y, "z": c4d.VECTOR_Z}
            did = c4d.DescID(
                c4d.DescLevel(int(pid), c4d.DTYPE_VECTOR, 0),
                c4d.DescLevel(cm[comp], c4d.DTYPE_REAL, 0),
            )

    im = {
        "linear": c4d.CINTERPOLATION_LINEAR,
        "spline": c4d.CINTERPOLATION_SPLINE,
        "step": c4d.CINTERPOLATION_STEP,
    }
    if interp_name not in im:
        raise ValueError(f"interp must be linear/spline/step, got {interp_name!r}")

    # Coerce the value to the underlying curve's expected scalar type.
    if effective_dtype == c4d.DTYPE_BOOL:
        coerced_value = bool(value)
    elif effective_dtype == c4d.DTYPE_LONG:
        if value != int(value) or not -(2**31) <= value < 2**31:
            raise ValueError("LONG keyframe value must be a signed 32-bit integer")
        coerced_value = float(int(value))
    else:
        coerced_value = float(value)

    doc.StartUndo()
    try:
        track = obj.FindCTrack(did)
        if track is None:
            track = c4d.CTrack(obj, did)
            obj.InsertTrackSorted(track)
            doc.AddUndo(c4d.UNDOTYPE_NEWOBJ, track)
        else:
            doc.AddUndo(c4d.UNDOTYPE_CHANGE, track)
        curve = track.GetCurve()
        kd = curve.AddKey(c4d.BaseTime(int(frame), int(fps)))
        key = kd["key"] if isinstance(kd, dict) else kd
        if track.GetTrackCategory() == c4d.CTRACK_CATEGORY_DATA:
            key.SetGeData(curve, coerced_value)
        else:
            key.SetValue(curve, coerced_value)
        key.SetInterpolation(curve, im[interp_name])
    finally:
        doc.EndUndo()
    c4d.EventAdd()
    return {
        "handle": h,
        "path": _descid_path(did),
        "frame": int(frame),
        "value": coerced_value,
        "interp": interp_name,
        "dtype": {
            c4d.DTYPE_REAL: "real",
            c4d.DTYPE_LONG: "long",
            c4d.DTYPE_BOOL: "bool",
            c4d.DTYPE_VECTOR: "vector",
        }.get(effective_dtype, str(effective_dtype)),
    }


def handle_delete_track(params: dict[str, Any]) -> dict[str, Any]:
    """Remove an entire CTrack from a target.

    params:
      handle:    target
      param_id:  top-level id
      component: "x"/"y"/"z"/null
    """
    h = params.get("handle")
    if not h:
        raise ValueError("handle required")
    did = _selector_path(params)
    obj = _resolve_handle(h)
    if obj is None:
        raise ValueError(f"handle not resolved: {h}")
    if not hasattr(obj, "GetCTracks"):
        raise ValueError(f"handle {h!r} has no animation tracks")

    track = _selected_track(obj, params, did)
    if track is None:
        return {"removed": False}

    doc = documents.GetActiveDocument()
    if doc is not None:
        doc.StartUndo()
        with contextlib.suppress(Exception):
            doc.AddUndo(c4d.UNDOTYPE_DELETE, track)
    try:
        track.Remove()
    finally:
        if doc is not None:
            doc.EndUndo()
    c4d.EventAdd()
    return {"removed": True}
