from __future__ import annotations

import copy
import importlib
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugin" / "cinema4d_mcp_bridge"
REAL, LONG, BOOL, VECTOR, SUBCONTAINER = 19, 15, 400006001, 23, 5
VALUE_CATEGORY, DATA_CATEGORY = 1, 2
HANDLE = {"kind": "object", "name": "Controller"}
USER_REAL = [[700, SUBCONTAINER, 0], [1, REAL, 0]]
USER_BOOL = [[700, SUBCONTAINER, 0], [2, BOOL, 0]]
USER_VECTOR_X = [[700, SUBCONTAINER, 0], [3, VECTOR, 0], [1000, REAL, 0]]


class FakeDescLevel:
    def __init__(self, param_id, dtype, creator):
        self.id, self.dtype, self.creator = param_id, dtype, creator


class FakeDescID:
    def __init__(self, *levels):
        if not 1 <= len(levels) <= 3:
            raise ValueError("DescID supports one to three levels")
        self.levels = levels

    def GetDepth(self):
        return len(self.levels)

    def __getitem__(self, index):
        return self.levels[index]

    def __eq__(self, other):
        return isinstance(other, FakeDescID) and [vars(x) for x in self.levels] == [
            vars(x) for x in other.levels
        ]


class FakeTime:
    def __init__(self, frame, fps):
        self.seconds = frame / fps

    def GetFrame(self, fps):
        return round(self.seconds * fps)


class FakeKey:
    def __init__(self, time, category):
        self.time, self.category = time, category
        self.value = None
        self.interp = None

    def GetTime(self):
        return self.time

    def SetValue(self, curve, value):
        if self.category != VALUE_CATEGORY:
            raise AssertionError("DATA keys require SetGeData")
        self.value = value

    def GetValue(self):
        if self.category != VALUE_CATEGORY:
            raise AssertionError("DATA keys require GetGeData")
        return self.value

    def SetGeData(self, curve, value):
        if self.category != DATA_CATEGORY:
            raise AssertionError("VALUE keys require SetValue")
        self.value = value

    def GetGeData(self):
        if self.category != DATA_CATEGORY:
            raise AssertionError("VALUE keys require GetValue")
        return self.value

    def SetInterpolation(self, curve, interpolation):
        self.interp = interpolation

    def GetInterpolation(self):
        return self.interp


class FakeCurve:
    def __init__(self, category):
        self.category = category
        self.keys = []

    def AddKey(self, time):
        key = next((key for key in self.keys if key.time.seconds == time.seconds), None)
        if key is None:
            key = FakeKey(time, self.category)
            self.keys.append(key)
            self.keys.sort(key=lambda item: item.time.seconds)
        return {"key": key, "nidx": self.keys.index(key)}

    def GetKeyCount(self):
        return len(self.keys)

    def GetKey(self, index):
        return self.keys[index]

    def DelKey(self, index):
        del self.keys[index]


class FakeTrack:
    def __init__(self, owner, desc_id):
        self.owner, self.desc_id = owner, desc_id
        self.category = DATA_CATEGORY if desc_id.levels[-1].dtype == BOOL else VALUE_CATEGORY
        self.curve = FakeCurve(self.category)

    def GetDescriptionID(self):
        return self.desc_id

    def GetName(self):
        return "Track"

    def GetCurve(self):
        return self.curve

    def GetTrackCategory(self):
        return self.category

    def Remove(self):
        self.owner.tracks.remove(self)


class FakeObject:
    def __init__(self):
        self.tracks = []

    def GetCTracks(self):
        return list(self.tracks)

    def FindCTrack(self, desc_id):
        return next((track for track in self.tracks if track.desc_id == desc_id), None)

    def InsertTrackSorted(self, track):
        self.tracks.append(track)


class AnimationTests(unittest.TestCase):
    def setUp(self):
        self.obj = FakeObject()
        self.undo_starts = 0
        self.undo_ends = 0
        self.undos = []
        self.events = 0
        self.doc = types.SimpleNamespace(
            GetFps=lambda: 30,
            StartUndo=self._start_undo,
            EndUndo=self._end_undo,
            AddUndo=self._add_undo,
        )
        c4d = types.ModuleType("c4d")
        for name, value in {
            "DTYPE_REAL": REAL,
            "DTYPE_LONG": LONG,
            "DTYPE_BOOL": BOOL,
            "DTYPE_VECTOR": VECTOR,
            "CINTERPOLATION_LINEAR": 0,
            "CINTERPOLATION_SPLINE": 1,
            "CINTERPOLATION_STEP": 2,
            "VECTOR_X": 1000,
            "VECTOR_Y": 1001,
            "VECTOR_Z": 1002,
            "CTRACK_CATEGORY_VALUE": VALUE_CATEGORY,
            "CTRACK_CATEGORY_DATA": DATA_CATEGORY,
            "UNDOTYPE_CHANGE": 40,
            "UNDOTYPE_DELETE": 45,
            "UNDOTYPE_NEWOBJ": 44,
            "DescID": FakeDescID,
            "DescLevel": FakeDescLevel,
            "CTrack": FakeTrack,
            "BaseTime": FakeTime,
            "EventAdd": self._event_add,
        }.items():
            setattr(c4d, name, value)
        c4d.documents = types.ModuleType("c4d.documents")
        c4d.documents.GetActiveDocument = lambda: self.doc
        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        helpers = types.ModuleType("bridge.handlers._helpers")
        helpers._resolve_handle = lambda handle: self.obj if handle == HANDLE else None
        helpers._param_dtype = lambda obj, pid: {903: VECTOR, 100: REAL, 101: BOOL}.get(pid)
        self.patcher = patch.dict(
            sys.modules,
            {
                "c4d": c4d,
                "c4d.documents": c4d.documents,
                "bridge": bridge,
                "bridge.handlers": handlers,
                "bridge.handlers._helpers": helpers,
            },
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        sys.modules.pop("bridge.handlers.animation", None)
        self.animation = importlib.import_module("bridge.handlers.animation")
        self.addCleanup(sys.modules.pop, "bridge.handlers.animation", None)

    def _start_undo(self):
        self.undo_starts += 1

    def _end_undo(self):
        self.undo_ends += 1

    def _event_add(self):
        self.events += 1

    def _add_undo(self, undo_type, track):
        self.assertIn(track, self.obj.tracks)
        self.undos.append((undo_type, track, copy.deepcopy(track.curve.keys)))

    def _undo_last(self):
        undo_type, track, previous_keys = self.undos.pop()
        if undo_type == 44:
            self.obj.tracks.remove(track)
        else:
            track.curve.keys = previous_keys

    def set_key(self, **params):
        return self.animation.handle_set_keyframe({"handle": HANDLE, **params})

    def get_keys(self, **params):
        return self.animation.handle_get_keyframes({"handle": HANDLE, **params})

    def test_legacy_scalar_vector_and_bool_remain_usable(self):
        for selector, value in [
            ({"param_id": 100}, 2.5),
            ({"param_id": 903, "component": "x"}, -4.0),
            ({"param_id": 101}, True),
        ]:
            with self.subTest(selector=selector):
                self.set_key(**selector, frame=12, value=value, interp="linear")
                result = self.get_keys(**selector)
                self.assertEqual(
                    result["keys"], [{"frame": 12, "value": value, "interp": "linear"}]
                )

    def test_full_user_data_paths_round_trip_and_update_same_key(self):
        for path, value in [(USER_REAL, 2.5), (USER_BOOL, True), (USER_VECTOR_X, -4.0)]:
            with self.subTest(path=path):
                self.set_key(path=path, frame=10, value=value, interp="step")
                self.assertEqual(self.get_keys(path=path)["keys"][0]["interp"], "step")
                self.set_key(path=path, frame=10, value=value, interp="linear")
                result = self.get_keys(path=path)
                self.assertEqual(result["track"]["path"], path)
                self.assertEqual(
                    result["keys"], [{"frame": 10, "value": value, "interp": "linear"}]
                )
        listed = self.animation.handle_list_tracks({"handle": HANDLE})
        self.assertEqual(listed["count"], 3)
        self.assertIsNone(listed["tracks"][0]["component"])
        for track in listed["tracks"]:
            self.assertEqual(self.get_keys(path=track["path"])["count"], 1)
        self.set_key(path=USER_BOOL, frame=20, value=False)
        self.assertIs(self.get_keys(path=USER_BOOL)["keys"][1]["value"], False)
        self.assertEqual(self.undo_starts, self.undo_ends)

    def test_exact_levels_and_creator_do_not_collide(self):
        alternate = [[700, SUBCONTAINER, 0], [1, REAL, 1234]]
        self.set_key(path=USER_REAL, frame=0, value=1)
        self.set_key(path=alternate, frame=0, value=2)
        self.assertEqual(self.get_keys(path=USER_REAL)["keys"][0]["value"], 1)
        self.assertEqual(self.get_keys(path=alternate)["keys"][0]["value"], 2)
        self.assertEqual(self.get_keys(param_id=700, component="x")["count"], 0)

    def test_full_path_delete_single_range_and_track_preserves_siblings(self):
        for frame in (0, 10, 20):
            self.set_key(path=USER_REAL, frame=frame, value=frame)
        self.set_key(path=USER_BOOL, frame=10, value=True)
        self.assertEqual(self.get_keys(path=USER_REAL, start_frame=5, end_frame=15)["count"], 1)
        single = self.animation.handle_delete_keyframe(
            {"handle": HANDLE, "path": USER_REAL, "frame": 10}
        )
        self.assertEqual(single["removed"], 1)
        ranged = self.animation.handle_delete_keyframe(
            {"handle": HANDLE, "path": USER_REAL, "start_frame": 0, "end_frame": 19}
        )
        self.assertEqual(ranged["removed"], 1)
        self.assertEqual(self.get_keys(path=USER_REAL)["keys"][0]["frame"], 20)
        removed = self.animation.handle_delete_track({"handle": HANDLE, "path": USER_REAL})
        self.assertTrue(removed["removed"])
        self.assertFalse(
            self.animation.handle_delete_track({"handle": HANDLE, "path": USER_REAL})["removed"]
        )
        self.assertEqual(self.get_keys(path=USER_BOOL)["count"], 1)

    def test_fps_override_and_long_value(self):
        self.set_key(path=[[100, LONG, 0]], frame=24, fps=24, value=7)
        self.assertEqual(self.get_keys(path=[[100, LONG, 0]], fps=48)["keys"][0]["frame"], 48)

    def test_new_track_and_existing_key_updates_record_undo_at_correct_time(self):
        self.set_key(path=USER_REAL, frame=0, value=1)
        self.assertEqual(self.undos[-1][0], 44)
        self.assertEqual(self.undos[-1][2], [])
        self.set_key(path=USER_REAL, frame=0, value=2)
        self.assertEqual(self.undos[-1][0], 40)
        self.assertEqual(self.undos[-1][2][0].value, 1)
        self._undo_last()
        self.assertEqual(self.get_keys(path=USER_REAL)["keys"][0]["value"], 1)
        self._undo_last()
        self.assertEqual(self.obj.tracks, [])

    def test_invalid_selectors_rejected_by_all_track_commands_before_mutation(self):
        invalid = [
            {},
            {"path": USER_REAL, "param_id": 700},
            {"path": USER_REAL, "component": "x"},
            {"path": []},
            {"path": [700, 1]},
            {"path": [[700, SUBCONTAINER]]},
            {"path": [[True, REAL, 0]]},
            {"path": [[1, REAL, 0]] * 4},
            {"path": [[1, REAL, math.inf]]},
            {"param_id": True},
            {"param_id": 1.5},
            {"param_id": 903, "component": "w"},
        ]
        for command in ("set_keyframe", "get_keyframes", "delete_keyframe", "delete_track"):
            for selector in invalid:
                with (
                    self.subTest(command=command, selector=selector),
                    self.assertRaises(ValueError),
                ):
                    getattr(self.animation, "handle_" + command)(
                        {"handle": HANDLE, "frame": 0, "value": 1, **selector}
                    )
        self.assertEqual(self.obj.tracks, [])
        self.assertEqual(self.undo_starts, 0)
        self.assertEqual(self.events, 0)

    def test_invalid_values_and_time_ranges_rejected_before_mutation(self):
        for overrides in (
            {"value": math.nan},
            {"value": math.inf},
            {"value": 10**400},
            {"value": "1"},
            {"frame": 0.5},
            {"frame": True},
            {"fps": 0},
            {"fps": math.inf},
            {"path": USER_REAL, "dtype": "long"},
            {"path": [[1, VECTOR, 0]]},
            {"path": [[1, LONG, 0]], "value": 1.5},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.set_key(**({"path": USER_REAL, "frame": 0, "value": 1} | overrides))
        for command in ("get_keyframes", "delete_keyframe"):
            for bounds in ({"start_frame": 2, "end_frame": 1}, {"start_frame": True}, {"fps": 0}):
                with self.subTest(command=command, bounds=bounds), self.assertRaises(ValueError):
                    getattr(self.animation, "handle_" + command)(
                        {"handle": HANDLE, "path": USER_REAL, **bounds}
                    )
        with self.assertRaises(ValueError):
            self.animation.handle_delete_keyframe(
                {"handle": HANDLE, "path": USER_REAL, "frame": 0, "end_frame": 1}
            )
        self.assertEqual(self.obj.tracks, [])
        self.assertEqual(self.undo_starts, 0)


if __name__ == "__main__":
    unittest.main()
