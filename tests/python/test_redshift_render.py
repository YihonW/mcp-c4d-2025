from __future__ import annotations

import contextlib
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from redshift_fakes import RS_RENDERER_ID, make_c4d_runtime, make_redshift_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin" / "cinema4d_mcp_bridge"


class FakeBaseTime:
    def __init__(self, frame, fps):
        self.frame = frame
        self.fps = fps

    def __eq__(self, other):
        return isinstance(other, FakeBaseTime) and (self.frame, self.fps) == (
            other.frame,
            other.fps,
        )


class FakeVideoPost:
    def __init__(self, values=None, fail_parameter=None):
        self.values = dict(values or {})
        self.fail_parameter = fail_parameter

    def SetParameter(self, parameter, value):
        if parameter == self.fail_parameter:
            raise RuntimeError("injected video post write failure")
        self.values[parameter] = value
        return True

    def GetClone(self):
        return FakeVideoPost(self.values)


class FakeRenderData:
    def __init__(self):
        self.name = ""
        self.values = {}
        self.next = None
        self.down = None
        self.document = None
        self.video_post = None

    def SetName(self, name):
        self.name = name

    def GetName(self):
        return self.name

    def GetNext(self):
        return self.next

    def GetDown(self):
        return self.down

    def __getitem__(self, parameter):
        return self.values.get(parameter)

    def __setitem__(self, parameter, value):
        self.values[parameter] = value

    def GetClone(self):
        copied = FakeRenderData()
        copied.name = self.name
        copied.values = dict(self.values)
        copied.video_post = self.video_post.GetClone() if self.video_post is not None else None
        return copied

    def CopyTo(self, target, _flags, _trans=None):
        target.name = self.name
        target.values = dict(self.values)
        target.video_post = self.video_post.GetClone() if self.video_post is not None else None
        return True

    def Remove(self):
        if self.document is not None:
            self.document.remove_render_data(self)


class FakeRenderDocument:
    def __init__(self, name):
        self.name = name
        self.next = None
        self.render_data = []
        self.active_render_data = None
        self.insert_calls = []
        self.active_changes = []

    def GetDocumentName(self):
        return self.name

    def GetNext(self):
        return self.next

    def GetFps(self):
        return 30

    def GetFirstRenderData(self):
        return self.render_data[0] if self.render_data else None

    def GetActiveRenderData(self):
        return self.active_render_data

    def SetActiveRenderData(self, render_data):
        self.active_render_data = render_data
        self.active_changes.append(render_data)

    def InsertRenderData(self, render_data):
        render_data.document = self
        self.render_data.append(render_data)
        self.insert_calls.append(render_data)
        self._relink()

    def remove_render_data(self, render_data):
        self.render_data.remove(render_data)
        render_data.document = None
        self._relink()

    def _relink(self):
        for index, render_data in enumerate(self.render_data):
            render_data.next = (
                self.render_data[index + 1] if index + 1 < len(self.render_data) else None
            )


class RedshiftRenderTest(unittest.TestCase):
    def setUp(self):
        self.c4d, self.documents, self.document_state, self.plugin_lookup = make_c4d_runtime(
            document_names=["placeholder"], plugins={RS_RENDERER_ID}
        )
        self._install_render_symbols()
        self.document = FakeRenderDocument("main")
        self.document_state.items = [self.document]
        self.document_state.active = self.document
        self.user_render_data = self._render_data("User")
        self.user_render_data[self.c4d.RDATA_RENDERENGINE] = 0
        self.document.InsertRenderData(self.user_render_data)
        self.document.active_render_data = self.user_render_data
        self.document.insert_calls.clear()

        self.redshift = make_redshift_runtime()
        self.find_video_post_calls = []
        self.return_none_video_post = False

        def find_video_post(render_data, renderer):
            self.find_video_post_calls.append((render_data, renderer))
            if self.return_none_video_post:
                return None
            if render_data.video_post is None:
                render_data.video_post = FakeVideoPost()
            return render_data.video_post

        self.redshift.FindAddVideoPost = find_video_post
        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        parent_helpers = types.ModuleType("bridge.handlers._helpers")
        parent_helpers._require_abs_path = self._require_abs_path
        parent_helpers._require_writable_path = self._require_writable_path
        self.modules = {
            "c4d": self.c4d,
            "c4d.documents": self.documents,
            "maxon": types.ModuleType("maxon"),
            "redshift": self.redshift,
            "bridge": bridge,
            "bridge.handlers": handlers,
            "bridge.handlers._helpers": parent_helpers,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        sys.path.insert(0, str(PLUGIN_ROOT))

    def tearDown(self):
        for name in tuple(sys.modules):
            if name.startswith("bridge.handlers.redshift"):
                sys.modules.pop(name, None)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(PLUGIN_ROOT))
        self.module_patch.stop()

    def _install_render_symbols(self):
        values = {
            "COPYFLAGS_0": 0,
            "FILTER_EXR": 1016606,
            "FILTER_JPG": 1104,
            "FILTER_PNG": 1023671,
            "FILTER_TIF": 1100,
            "RDATA_FORMAT": 5033,
            "RDATA_FRAMEFROM": 5017,
            "RDATA_FRAMESEQUENCE": 5016,
            "RDATA_FRAMESEQUENCE_CURRENTFRAME": 1,
            "RDATA_FRAMETO": 5018,
            "RDATA_MULTIPASS_FILENAME": 5206,
            "RDATA_MULTIPASS_SAVEFORMAT": 5203,
            "RDATA_PATH": 5041,
            "RDATA_RENDERENGINE": 5300,
            "RDATA_XRES": 5008,
            "RDATA_YRES": 5009,
        }
        for name, value in values.items():
            setattr(self.c4d, name, value)
        self.c4d.BaseTime = FakeBaseTime
        self.documents.RenderData = FakeRenderData

    @staticmethod
    def _require_abs_path(value, **_kwargs):
        if not isinstance(value, str) or not os.path.isabs(value):
            raise ValueError("path must be absolute")
        return value

    @classmethod
    def _require_writable_path(cls, value):
        path = cls._require_abs_path(value)
        if not os.path.isdir(os.path.dirname(path)):
            raise ValueError("parent directory does not exist")
        return path

    @staticmethod
    def _render_data(name):
        render_data = FakeRenderData()
        render_data.SetName(name)
        return render_data

    def _load(self):
        return importlib.import_module("bridge.handlers.redshift.render")

    def test_create_configures_exact_redshift_fields_without_implicit_activation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            beauty_path = os.path.join(temp_dir, "beauty.exr")
            multipass_path = os.path.join(temp_dir, "aovs.exr")
            render = self._load()

            result = render.handle_rs_configure_render(
                {
                    "document_name": "main",
                    "name": "RS Final",
                    "width": 64,
                    "height": 32,
                    "frame": 7,
                    "output_format": "exr",
                    "beauty_path": beauty_path,
                    "multipass_path": multipass_path,
                    "redshift_params": {"9001": 1.5},
                }
            )

        created = self.document.render_data[-1]
        self.assertTrue(result["created"])
        self.assertFalse(result["active"])
        self.assertEqual(result["renderer_id"], RS_RENDERER_ID)
        self.assertEqual(result["video_post_id"], RS_RENDERER_ID)
        self.assertIs(self.document.active_render_data, self.user_render_data)
        self.assertEqual(created[self.c4d.RDATA_RENDERENGINE], RS_RENDERER_ID)
        self.assertEqual(created[self.c4d.RDATA_XRES], 64.0)
        self.assertEqual(created[self.c4d.RDATA_YRES], 32.0)
        self.assertEqual(created[self.c4d.RDATA_FRAMESEQUENCE], 1)
        self.assertEqual(created[self.c4d.RDATA_FRAMEFROM], FakeBaseTime(7, 30))
        self.assertEqual(created[self.c4d.RDATA_FRAMETO], FakeBaseTime(7, 30))
        self.assertEqual(created[self.c4d.RDATA_FORMAT], self.c4d.FILTER_EXR)
        self.assertEqual(created[self.c4d.RDATA_MULTIPASS_SAVEFORMAT], self.c4d.FILTER_EXR)
        self.assertEqual(created[self.c4d.RDATA_PATH], beauty_path)
        self.assertEqual(created[self.c4d.RDATA_MULTIPASS_FILENAME], multipass_path)
        self.assertEqual(created.video_post.values[9001], 1.5)

    def test_update_is_unique_and_only_activates_when_requested(self):
        target = self._render_data("Target")
        self.document.InsertRenderData(target)
        before_insert_count = len(self.document.insert_calls)
        render = self._load()

        result = render.handle_rs_configure_render(
            {"name": "Target", "update_if_exists": True, "make_active": True, "width": 100}
        )

        self.assertFalse(result["created"])
        self.assertTrue(result["active"])
        self.assertIs(self.document.active_render_data, target)
        self.assertEqual(len(self.document.insert_calls), before_insert_count)
        self.assertEqual(target[self.c4d.RDATA_XRES], 100.0)

    def test_duplicate_and_invalid_input_fail_before_any_write(self):
        first = self._render_data("Dup")
        second = self._render_data("Dup")
        self.document.InsertRenderData(first)
        self.document.InsertRenderData(second)
        insert_count = len(self.document.insert_calls)
        render = self._load()

        with self.assertRaisesRegex(ValueError, "already exists"):
            render.handle_rs_configure_render({"name": "Dup"})
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            render.handle_rs_configure_render({"name": "Dup", "update_if_exists": True})
        with self.assertRaisesRegex(ValueError, "redshift_params"):
            render.handle_rs_configure_render({"name": "New", "redshift_params": {"bad": []}})

        self.assertEqual(len(self.document.insert_calls), insert_count)
        self.assertEqual(self.find_video_post_calls, [])

    def test_invalid_output_path_and_missing_video_post_api_are_zero_write(self):
        render = self._load()
        insert_count = len(self.document.insert_calls)

        with self.assertRaisesRegex(ValueError, "parent directory"):
            render.handle_rs_configure_render(
                {"name": "Bad Path", "beauty_path": os.path.join("C:\\missing-parent", "x.png")}
            )
        del self.redshift.FindAddVideoPost
        with self.assertRaisesRegex(RuntimeError, "FindAddVideoPost"):
            render.handle_rs_configure_render({"name": "Missing API"})

        self.assertEqual(len(self.document.insert_calls), insert_count)

    def test_missing_shared_render_capability_is_zero_write(self):
        self.plugin_lookup.available.clear()
        render = self._load()
        insert_count = len(self.document.insert_calls)

        with self.assertRaisesRegex(RuntimeError, "render"):
            render.handle_rs_configure_render({"name": "Unavailable"})

        self.assertEqual(len(self.document.insert_calls), insert_count)
        self.assertEqual(self.find_video_post_calls, [])

    def test_existing_update_rolls_back_clone_after_late_video_post_error(self):
        target = self._render_data("Target")
        target[self.c4d.RDATA_RENDERENGINE] = 7
        target[self.c4d.RDATA_XRES] = 100.0
        target.video_post = FakeVideoPost({9000: "original"}, fail_parameter=9001)
        self.document.InsertRenderData(target)
        render = self._load()

        with self.assertRaisesRegex(RuntimeError, "rollback=succeeded"):
            render.handle_rs_configure_render(
                {
                    "name": "Target",
                    "update_if_exists": True,
                    "width": 200,
                    "redshift_params": {"9001": 2.0},
                }
            )

        self.assertEqual(target[self.c4d.RDATA_RENDERENGINE], 7)
        self.assertEqual(target[self.c4d.RDATA_XRES], 100.0)
        self.assertEqual(target.video_post.values, {9000: "original"})
        self.assertIs(self.document.active_render_data, self.user_render_data)

    def test_new_render_data_is_removed_after_video_post_failure(self):
        self.return_none_video_post = True
        render = self._load()

        with self.assertRaisesRegex(RuntimeError, "rollback=succeeded"):
            render.handle_rs_configure_render({"name": "New Fail"})

        self.assertEqual([item.GetName() for item in self.document.render_data], ["User"])
        self.assertIs(self.document.active_render_data, self.user_render_data)


if __name__ == "__main__":
    unittest.main()
