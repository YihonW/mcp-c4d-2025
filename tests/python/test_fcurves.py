from __future__ import annotations

import copy
import importlib
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_animation import FakeDescID, FakeDescLevel

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugin" / "cinema4d_mcp_bridge"
HANDLE = {"kind": "object", "name": "Controller"}
PATH = [[700, 5, 0], [1, 19, 0]]
SYMBOLS = {
    "DTYPE_REAL": 19,
    "DTYPE_LONG": 15,
    "DTYPE_BOOL": 400006001,
    "DTYPE_VECTOR": 23,
    "CINTERPOLATION_LINEAR": 0,
    "CINTERPOLATION_SPLINE": 1,
    "CINTERPOLATION_STEP": 2,
    "VECTOR_X": 1000,
    "VECTOR_Y": 1001,
    "VECTOR_Z": 1002,
    "CTRACK_CATEGORY_VALUE": 1,
    "CTRACK_CATEGORY_DATA": 2,
    "CCURVE_CURVE": 1,
    "UNDOTYPE_CHANGE": 40,
    "COPYFLAGS_NONE": 0,
    "CTtime": -1,
    "NBIT_CKEY_AUTO": 46,
    "NBIT_CKEY_BREAK": 42,
    "NBIT_CKEY_CLAMP": 41,
    "NBIT_CKEY_AUTOWEIGHT": 86,
    "NBIT_CKEY_REMOVEOVERSHOOT": 85,
    "NBIT_CKEY_LOCK_O": 44,
    "NBIT_CKEY_LOCK_L": 45,
    "NBIT_CKEY_KEEPVISUALANGLE": 43,
    "NBIT_CKEY_LOCK_T": 38,
    "NBIT_CKEY_LOCK_V": 39,
    "NBIT_CKEY_WEIGHTEDTANGENT": 84,
    "NBITCONTROL_SET": 1,
    "NBITCONTROL_CLEAR": 2,
    "CLOOP_OFF": 0,
    "CLOOP_CONSTANT": 1,
    "CLOOP_CONTINUE": 2,
    "CLOOP_REPEAT": 3,
    "CLOOP_OFFSETREPEAT": 4,
    "CLOOP_OSCILLATE": 5,
    "CLOOP_LOOP": 6,
    "ID_BASEOBJECT_QUATERNION_ROTATION": 806,
    "ID_CTRACK_CONSTANTVELOCITY_V": 918,
    "DESCFLAGS_GET_0": 0,
}


class Time:
    def __init__(self, numerator=0, denominator=1):
        self.seconds = numerator / denominator

    def Get(self):
        return self.seconds

    def GetFrame(self, fps):
        raise AssertionError("F-Curves must not round subframes with GetFrame")

    def __eq__(self, other):
        return isinstance(other, Time) and self.seconds == other.seconds


class Key:
    def __init__(self, frame, value, auto=False):
        self.time = Time(frame, 30)
        self.value = value
        self.interp = 1
        self.left, self.right = [-1 / 30, -1.0], [1 / 30, 1.0]
        self.bits = {SYMBOLS["NBIT_CKEY_AUTO"]} if auto else {SYMBOLS["NBIT_CKEY_BREAK"]}

    def GetTime(self):
        return self.time

    def GetValue(self):
        return self.value

    def GetInterpolation(self):
        return self.interp

    def GetNBit(self, bit):
        return bit in self.bits

    def GetClone(self, trans=None):
        return copy.deepcopy(self)

    def SetValue(self, curve, value):
        self.value = value

    def SetInterpolation(self, curve, interp):
        self.interp = interp

    def SetTime(self, curve, time):
        self.time = time

    def SetTimeLeft(self, curve, time):
        self.left[0] = time.Get()

    def SetTimeRight(self, curve, time):
        self.right[0] = time.Get()

    def SetValueLeft(self, curve, value):
        self.left[1] = value

    def SetValueRight(self, curve, value):
        self.right[1] = value

    def ChangeNBit(self, bit, mode):
        if mode == SYMBOLS["NBITCONTROL_SET"]:
            self.bits.add(bit)
        else:
            self.bits.discard(bit)
        return bit in self.bits  # False when clearing is success, not an API failure.


class Curve:
    def __init__(self, keys):
        self.keys = keys
        self.dirty = 0

    def GetKeyCount(self):
        return len(self.keys)

    def GetKey(self, index):
        return self.keys[index]

    def SetKeyDirty(self):
        self.dirty += 1

    def GetTangents(self, index):
        key = self.keys[index]
        if key.GetNBit(SYMBOLS["NBIT_CKEY_AUTO"]):
            return (-2.0, 2.0, -2 / 30, 2 / 30)
        if key.GetNBit(SYMBOLS["NBIT_CKEY_CLAMP"]):
            return (0.0, 0.0, key.left[0], key.right[0])
        return key.left[1], key.right[1], key.left[0], key.right[0]

    def FlushKeys(self, undo=False, synchronize=False):
        assert undo is False and synchronize is False
        self.keys.clear()

    def InsertKey(self, key, undo=False, synchronize=False):
        assert undo is False and synchronize is False
        # Simulate the destructive replacement native insert can cause at equal time.
        self.keys = [old for old in self.keys if old.GetTime() != key.GetTime()]
        self.keys.append(key)
        self.keys.sort(key=lambda item: item.GetTime().Get())
        return True


class Track:
    def __init__(self, owner, keys, controls):
        self.owner = owner
        self.curve = Curve(keys)
        self.controls = controls
        self.did = FakeDescID(*(FakeDescLevel(*level) for level in PATH))
        self.category = 1
        self.type_id = 5350
        self.synchronized = False
        self.time_track = None
        self.parameters = {}
        self.before, self.after = 1, 1
        self.layer = object()

    def GetName(self):
        return "Control curve"

    def GetDescriptionID(self):
        return self.did

    def GetTrackCategory(self):
        return self.category

    def GetType(self):
        return self.type_id

    def GetObject(self):
        return self.owner

    def GetDocument(self):
        return self.owner.doc if self.owner else None

    def GetBefore(self):
        return self.before

    def GetAfter(self):
        return self.after

    def SetBefore(self, mode):
        self.before = mode

    def SetAfter(self, mode):
        self.after = mode

    def IsSynchronized(self):
        return self.synchronized

    def GetTimeTrack(self, doc):
        return self.time_track

    def GetParameter(self, param, flags):
        assert isinstance(param, FakeDescID)
        return self.parameters.get(param[0].id, False)

    def GetLayerObject(self, doc):
        return self.layer

    def GetPred(self):
        if not self.owner:
            return None
        index = self.owner.tracks.index(self)
        return self.owner.tracks[index - 1] if index else None

    def GetNext(self):
        if not self.owner:
            return None
        index = self.owner.tracks.index(self)
        return self.owner.tracks[index + 1] if index + 1 < len(self.owner.tracks) else None

    def GetCurve(self, kind=1, create=True):
        self.controls["curve_calls"].append((kind, create))
        if self.curve is None and create:
            self.curve = Curve([])
        return self.curve

    def GetClone(self, flags, trans=None):
        self.controls["clones"] += 1
        if self.controls.get("clone_none"):
            return None
        clone = copy.copy(self)
        clone.owner = None
        clone.curve = copy.deepcopy(self.curve)
        return clone

    def CopyTo(self, destination, flags, trans=None):
        assert flags == 0 and trans is None
        if destination.owner:
            self.controls["live_copies"] += 1
        if self.controls.get("copy_noop") or (
            self.controls.get("rollback_noop") and self.controls["live_copies"] > 1
        ):
            return True
        destination.curve = copy.deepcopy(self.curve)
        destination.before, destination.after = self.before, self.after
        destination.layer = self.layer
        remaining = self.controls.get("copy_failures", 0)
        if remaining:
            self.controls["copy_failures"] = remaining - 1
            destination.curve.keys[0].value = -999  # Partial native failure.
            return False
        return True

    def GetValue(self, doc, time, fps):
        self.controls["samples"].append((doc, time.Get(), fps))
        return time.Get() * 7  # Proves SDK forwarding, not real C4D evaluation behavior.


class FCurveTests(unittest.TestCase):
    def setUp(self):
        self.controls = {"curve_calls": [], "clones": 0, "live_copies": 0, "samples": []}
        self.undo_starts = self.undo_ends = self.events = 0
        self.undo_snapshots = []
        self.doc = types.SimpleNamespace(
            GetName=lambda: " Exact Scene ",
            GetFps=lambda: 30,
            GetNext=lambda: None,
            StartUndo=self.start_undo,
            EndUndo=self.end_undo,
            AddUndo=self.add_undo,
        )
        self.obj = types.SimpleNamespace(doc=self.doc, tracks=[], quaternion=False)
        self.obj.GetDocument = lambda: self.doc
        self.obj.GetCTracks = lambda: list(self.obj.tracks)
        self.obj.FindCTrack = lambda did: next(
            (track for track in self.obj.tracks if track.did == did), None
        )
        self.obj.GetParameter = self.object_parameter
        self.track = Track(self.obj, [Key(0.25, 1), Key(10.75, 4), Key(20.5, 8)], self.controls)
        self.obj.tracks = [self.track]
        self.c4d = types.ModuleType("c4d")
        for name, value in SYMBOLS.items():
            setattr(self.c4d, name, value)
        self.c4d.DescID, self.c4d.DescLevel, self.c4d.BaseTime = FakeDescID, FakeDescLevel, Time
        self.c4d.EventAdd = self.event_add
        self.c4d.documents = types.SimpleNamespace(
            GetActiveDocument=lambda: self.doc, GetFirstDocument=lambda: self.doc
        )
        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        helpers = types.ModuleType("bridge.handlers._helpers")
        helpers._resolve_handle = lambda handle: self.obj if handle == HANDLE else None
        helpers._param_dtype = lambda obj, pid: 19
        patcher = patch.dict(
            sys.modules,
            {
                "c4d": self.c4d,
                "c4d.documents": self.c4d.documents,
                "bridge": bridge,
                "bridge.handlers": handlers,
                "bridge.handlers._helpers": helpers,
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("bridge.handlers.animation", "bridge.handlers.fcurves"):
            sys.modules.pop(name, None)
            self.addCleanup(sys.modules.pop, name, None)
        self.module = importlib.import_module("bridge.handlers.fcurves")

    def start_undo(self):
        self.undo_starts += 1
        return True

    def object_parameter(self, param, flags):
        self.assertIsInstance(param, FakeDescID)
        return self.obj.quaternion

    def end_undo(self):
        self.undo_ends += 1
        return True

    def event_add(self):
        self.events += 1

    def add_undo(self, kind, track):
        self.assertEqual(kind, 40)
        self.assertIs(track, self.track)
        self.undo_snapshots.append(copy.deepcopy(track.curve.keys))
        return True

    def call(self, command, **params):
        return getattr(self.module, "handle_" + command)(
            {"document_name": " Exact Scene ", "handle": HANDLE, "path": PATH, **params}
        )

    def assert_no_live_writes(self):
        self.assertEqual(self.controls["live_copies"], 0)
        self.assertEqual(self.undo_starts, 0)
        self.assertEqual(self.events, 0)

    def test_reader_keeps_subframes_and_reads_effective_tangents_without_creating(self):
        self.track.curve.keys[0].bits.add(SYMBOLS["NBIT_CKEY_AUTO"])
        result = self.call("get_fcurve", sample_frames=[0.125, 25.5])
        self.assertEqual([key["frame"] for key in result["keys"]], [0.25, 10.75, 20.5])
        self.assertEqual(result["keys"][0]["left"], {"dt_frames": -2, "dv": -2})
        self.assertEqual(result["keys"][0]["tangent_mode"], "auto")
        self.assertEqual(result["samples"][0]["frame"], 0.125)
        self.assertAlmostEqual(result["samples"][0]["value"], 0.125 / 30 * 7)
        self.assertEqual(result["before"], "constant")
        self.assertTrue(all(call == (1, False) for call in self.controls["curve_calls"]))
        self.assertEqual(self.controls["clones"], 0)
        self.assert_no_live_writes()

    def test_reader_refuses_missing_curve_without_creating(self):
        self.track.curve = None
        with self.assertRaisesRegex(ValueError, "[Cc]urve"):
            self.call("get_fcurve")
        self.assertIsNone(self.track.curve)
        self.assert_no_live_writes()

    def test_manual_edit_disables_interfering_flags_and_preserves_owner_siblings(self):
        key = self.track.curve.keys[0]
        for name in (
            "AUTO",
            "CLAMP",
            "AUTOWEIGHT",
            "REMOVEOVERSHOOT",
            "LOCK_O",
            "LOCK_L",
            "KEEPVISUALANGLE",
            "WEIGHTEDTANGENT",
        ):
            key.bits.add(SYMBOLS["NBIT_CKEY_" + name])
        sibling = Track(self.obj, [Key(0, 9)], self.controls)
        sibling.did = FakeDescID(FakeDescLevel(123, 19, 0))
        self.obj.tracks.append(sibling)
        layer = self.track.layer
        result = self.call(
            "edit_fcurve_keys",
            edits=[
                {
                    "key_index": 0,
                    "value": 3.5,
                    "interp": "spline",
                    "tangent_mode": "manual",
                    "left": {"dt_frames": -0.5, "dv": -3},
                    "right": {"dt_frames": 0.75, "dv": 4},
                }
            ],
        )
        self.assertEqual(result["keys"][0]["left"], {"dt_frames": -0.5, "dv": -3})
        self.assertEqual(result["keys"][0]["right"], {"dt_frames": 0.75, "dv": 4})
        self.assertFalse(self.track.curve.keys[0].GetNBit(SYMBOLS["NBIT_CKEY_AUTO"]))
        self.assertTrue(self.track.curve.keys[0].GetNBit(SYMBOLS["NBIT_CKEY_WEIGHTEDTANGENT"]))
        self.assertIs(self.track.GetObject(), self.obj)
        self.assertIs(self.track.GetNext(), sibling)
        self.assertIs(self.track.layer, layer)
        self.assertEqual(self.undo_snapshots[0][0].value, 1)
        self.assertEqual(self.undo_starts, self.undo_ends)
        self.call("edit_fcurve_keys", edits=[{"key_index": 0, "tangent_mode": "auto"}])
        self.assertTrue(self.track.curve.keys[0].GetNBit(SYMBOLS["NBIT_CKEY_AUTO"]))

    def test_transform_scales_manual_offsets_preserves_auto_and_keeps_all_keys(self):
        self.track.curve.keys[1].bits.add(SYMBOLS["NBIT_CKEY_AUTO"])
        result = self.call(
            "transform_fcurve", time_scale=2, time_offset_frames=0.5, value_scale=-2, value_offset=1
        )
        self.assertEqual([key["frame"] for key in result["keys"]], [1, 22, 41.5])
        self.assertEqual([key["value"] for key in result["keys"]], [-1, -7, -15])
        self.assertEqual(result["keys"][0]["left"], {"dt_frames": -2, "dv": 2})
        self.assertEqual(result["keys"][1]["tangent_mode"], "auto")

    def test_manual_takeover_preserves_unsupplied_effective_side_not_hidden_raw_side(self):
        self.track.curve.keys[0].bits.add(SYMBOLS["NBIT_CKEY_AUTO"])
        result = self.call(
            "edit_fcurve_keys",
            edits=[
                {
                    "key_index": 0,
                    "tangent_mode": "manual",
                    "right": {"dt_frames": 0.5, "dv": 3},
                }
            ],
        )
        self.assertEqual(result["keys"][0]["left"], {"dt_frames": -2, "dv": -2})
        self.assertEqual(result["keys"][0]["right"], {"dt_frames": 0.5, "dv": 3})

    def test_transform_selection_crossing_unselected_keys_does_not_replace_them(self):
        result = self.call("transform_fcurve", key_indices=[0], time_offset_frames=12)
        self.assertEqual([key["frame"] for key in result["keys"]], [10.75, 12.25, 20.5])
        self.assertEqual([key["value"] for key in result["keys"]], [4, 1, 8])

    def test_collision_and_derived_overflow_reject_before_undo(self):
        for params in (
            {"key_indices": [0], "time_offset_frames": 10.5},
            {"value_scale": 1e308},
            {"time_scale": 1e6},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.call("transform_fcurve", **params)
        self.assert_no_live_writes()

    def test_extrapolation_maps_official_symbols_and_preserves_unsupplied_side(self):
        for name, constant in (
            ("off", 0),
            ("constant", 1),
            ("linear", 2),
            ("repeat", 3),
            ("offset_repeat", 4),
            ("oscillate", 5),
        ):
            self.call("set_track_extrapolation", after=name)
            self.assertEqual(self.track.after, constant)
            self.assertEqual(self.track.before, 1)

    def test_copy_failure_restores_native_snapshot_and_reports_failure(self):
        self.controls["copy_failures"] = 1
        with self.assertRaisesRegex(RuntimeError, "restor"):
            self.call("edit_fcurve_keys", edits=[{"key_index": 0, "value": 50}])
        self.assertEqual([key.value for key in self.track.curve.keys], [1, 4, 8])
        self.assertEqual(self.controls["live_copies"], 2)
        self.assertEqual(self.undo_starts, self.undo_ends)

    def test_failed_rollback_explicitly_reports_non_atomic_result(self):
        self.controls["copy_failures"] = 2
        with self.assertRaisesRegex(RuntimeError, "partial|non.atomic|rollback failed"):
            self.call("set_track_extrapolation", after="repeat")

    def test_silent_setter_and_partial_successful_copy_are_not_reported_as_success(self):
        with (
            patch.object(Key, "SetValue", lambda *args: None),
            self.assertRaisesRegex(RuntimeError, "verif|mismatch|apply"),
        ):
            self.call("edit_fcurve_keys", edits=[{"key_index": 0, "value": 99}])
        self.assert_no_live_writes()
        self.controls["copy_noop"] = True
        with self.assertRaisesRegex(RuntimeError, "restor"):
            self.call("edit_fcurve_keys", edits=[{"key_index": 0, "value": 99}])
        self.assertEqual(self.track.curve.keys[0].value, 1)

    def test_rollback_must_restore_content_not_only_return_true(self):
        self.controls["copy_failures"] = 1
        self.controls["rollback_noop"] = True
        with self.assertRaisesRegex(RuntimeError, "rollback failed|partial|non.atomic"):
            self.call("edit_fcurve_keys", edits=[{"key_index": 0, "value": 99}])

    def test_document_type_coupling_and_output_limits_fail_closed(self):
        for field, value in (
            ("category", 2),
            ("type_id", -1),
            ("synchronized", True),
            ("time_track", object()),
        ):
            old = getattr(self.track, field)
            setattr(self.track, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.call("get_fcurve")
            setattr(self.track, field, old)
        for name in ("Wrong", "Exact Scene", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.call("get_fcurve", document_name=name)
        self.track.curve.keys = [Key(index, 0) for index in range(1001)]
        with self.assertRaises(ValueError):
            self.call("get_fcurve")
        self.assert_no_live_writes()

    def test_strict_edit_validation_happens_before_any_write(self):
        invalid = [
            [],
            [{"key_index": 0}],
            [{"key_index": True, "value": 1}],
            [{"key_index": 3, "value": 1}],
            [{"key_index": 0, "value": math.inf}],
            [{"key_index": 0, "value": 1, "typo": True}],
            [{"key_index": 0, "value": 1}, {"key_index": 0, "interp": "step"}],
            [{"key_index": 0, "left": {"dt_frames": -1, "dv": 2}}],
            [{"key_index": 0, "tangent_mode": "manual", "left": {"dt_frames": 0, "dv": 2}}],
            [{"key_index": 0, "tangent_mode": "manual", "right": {"dt_frames": -1, "dv": 2}}],
        ]
        for edits in invalid:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                self.call("edit_fcurve_keys", edits=edits)
        self.assert_no_live_writes()

    def test_strict_transform_sample_and_extrapolation_inputs(self):
        for params in (
            {},
            {"key_indices": [0]},
            {"time_scale": 0},
            {"time_scale": -1},
            {"time_scale": True},
            {"time_scale": 1e7},
            {"time_offset_frames": 1e7},
            {"key_indices": [0, 0], "value_scale": 1},
            {"value_offset": 1, "typo": 0},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.call("transform_fcurve", **params)
        for frames in ([], [math.nan], [True], [1e7], [0] * 301):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                self.call("get_fcurve", sample_frames=frames)
        for params in ({}, {"before": "bogus"}, {"after": "repeat", "typo": 1}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.call("set_track_extrapolation", **params)
        self.assert_no_live_writes()

    def test_duplicate_document_name_is_rejected_without_switching(self):
        duplicate = types.SimpleNamespace(GetName=self.doc.GetName, GetNext=lambda: None)
        self.doc.GetNext = lambda: duplicate
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.call("get_fcurve")
        self.assertIs(self.c4d.documents.GetActiveDocument(), self.doc)
        self.assert_no_live_writes()

    def test_missing_sdk_snapshot_and_coupled_manual_flags_fail_before_undo(self):
        with (
            patch.object(self.track, "IsSynchronized", None),
            self.assertRaisesRegex(RuntimeError, "SDK"),
        ):
            self.call("get_fcurve")
        self.controls["clone_none"] = True
        with self.assertRaisesRegex(RuntimeError, "snapshot"):
            self.call("edit_fcurve_keys", edits=[{"key_index": 0, "value": 10}])
        self.controls["clone_none"] = False
        self.track.curve.keys[0].bits.add(SYMBOLS["NBIT_CKEY_CLAMP"])
        with self.assertRaisesRegex(ValueError, "interfering"):
            self.call("transform_fcurve", key_indices=[0], value_scale=2)
        self.assert_no_live_writes()

    def test_identity_transform_is_noop_and_pivots_allow_zero_value_scale(self):
        self.call("transform_fcurve", time_scale=1, pivot_frame=37, value_pivot=-19)
        self.assert_no_live_writes()
        self.assertEqual(self.controls["clones"], 0)
        result = self.call(
            "transform_fcurve",
            key_indices=[1],
            time_scale=2,
            pivot_frame=10.75,
            time_offset_frames=-0.5,
            value_scale=0,
            value_pivot=99,
            value_offset=-1,
        )
        self.assertEqual(result["keys"][1]["frame"], 10.25)
        self.assertEqual(result["keys"][1]["value"], 98)
        self.assertEqual(result["keys"][1]["left"]["dv"], 0)
        self.assertEqual(result["keys"][0]["value"], 1)

    def test_legacy_scalar_and_vector_selectors_remain_supported(self):
        for path, selector in (
            ([[100, 19, 0]], {"param_id": 100}),
            ([[903, 23, 0], [1000, 19, 0]], {"param_id": 903, "component": "x"}),
        ):
            self.track.did = FakeDescID(*(FakeDescLevel(*level) for level in path))
            result = self.module.handle_get_fcurve(
                {
                    "document_name": " Exact Scene ",
                    "handle": HANDLE,
                    **selector,
                }
            )
            self.assertEqual(result["path"], path)
            self.assertEqual(result["key_count"], 3)
        self.assert_no_live_writes()


if __name__ == "__main__":
    unittest.main()
