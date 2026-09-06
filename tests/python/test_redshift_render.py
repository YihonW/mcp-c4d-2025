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
    def __init__(self, values=None, fail_parameter=None, type_id=RS_RENDERER_ID):
        self.values = dict(values or {})
        self.fail_parameter = fail_parameter
        self.type_id = type_id
        self.next = None
        self.set_parameter_calls = []

    def GetType(self):
        return self.type_id

    def GetNext(self):
        return self.next

    def SetParameter(self, parameter, value, flags):
        self.set_parameter_calls.append((parameter, value, flags))
        if parameter == self.fail_parameter:
            raise RuntimeError("injected video post write failure")
        self.values[parameter] = value
        return True

    def GetClone(self):
        return FakeVideoPost(self.values, type_id=self.type_id)


class FakeContainer:
    def __init__(self, values):
        self.values = values

    def __iter__(self):
        return iter(self.values.items())


class FakeAov:
    def __init__(self, values):
        self.values = dict(values)

    def GetParameter(self, parameter):
        return self.values.get(parameter)

    def GetDataInstance(self):
        return FakeContainer(self.values)


class FakeBitmap:
    def __init__(self, owner, width, height, color_mode):
        self.owner = owner
        self.width = width
        self.height = height
        self.color_mode = color_mode
        self.channels = []

    def AddChannel(self, alpha, straight):
        self.channels.append((alpha, straight))

    def Save(self, path, output_format):
        self.owner.save_calls.append((path, output_format))
        if self.owner.save_result != self.owner.c4d.IMAGERESULT_OK:
            return self.owner.save_result
        Path(path).write_bytes(b"beauty-output")
        return self.owner.save_result


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

    def GetDataInstance(self):
        return self.values

    def GetFirstVideoPost(self):
        return self.video_post

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
        self.time = FakeBaseTime(3, 30)
        self.time_changes = []
        self.execute_calls = []
        self.execute_render_data = []
        self.execute_results = []

    def GetDocumentName(self):
        return self.name

    def GetNext(self):
        return self.next

    def GetFps(self):
        return 30

    def GetTime(self):
        return self.time

    def SetTime(self, value):
        self.time = value
        self.time_changes.append(value)

    def ExecutePasses(self, thread, animation, expressions, caches, flags):
        self.execute_calls.append((self.time, thread, animation, expressions, caches, flags))
        self.execute_render_data.append(self.GetActiveRenderData())
        result = self.execute_results.pop(0) if self.execute_results else True
        if isinstance(result, Exception):
            raise result
        return result

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
        self.aovs = []
        self.render_calls = []
        self.render_times = []
        self.expected_render_data = None
        self.render_exception = None
        self.render_result = self.c4d.RENDERRESULT_OK
        self.allocate_bitmap = True
        self.save_calls = []
        self.save_result = self.c4d.IMAGERESULT_OK
        self.write_aov_outputs = True

        def find_video_post(render_data, renderer):
            self.find_video_post_calls.append((render_data, renderer))
            if self.return_none_video_post:
                return None
            if render_data.video_post is None:
                render_data.video_post = FakeVideoPost()
            return render_data.video_post

        self.redshift.FindAddVideoPost = find_video_post

        def get_aovs(video_post):
            self.assertIs(
                self.document_state.active.GetActiveRenderData(), self.expected_render_data
            )
            self.assertIs(video_post, self.expected_render_data.video_post)
            return list(self.aovs)

        self.redshift.RendererGetAOVs = get_aovs
        self.c4d.bitmaps = types.SimpleNamespace(
            MultipassBitmap=lambda width, height, color_mode: (
                FakeBitmap(self, width, height, color_mode) if self.allocate_bitmap else None
            )
        )

        def render_document(document, settings, bitmap, flags):
            self.assertIs(document.GetActiveRenderData(), self.expected_render_data)
            self.render_calls.append((document, settings, bitmap, flags))
            self.render_times.append(document.GetTime())
            if self.render_exception is not None:
                raise self.render_exception
            if self.render_result == self.c4d.RENDERRESULT_OK and self.write_aov_outputs:
                for aov in self.aovs:
                    if aov.GetParameter(self.c4d.REDSHIFT_AOV_ENABLED) and aov.GetParameter(
                        self.c4d.REDSHIFT_AOV_FILE_ENABLED
                    ):
                        path = aov.GetParameter(self.c4d.REDSHIFT_AOV_FILE_EFFECTIVE_PATH)
                        if path:
                            Path(path).write_bytes(b"aov-output")
            return self.render_result

        self.documents.RenderDocument = render_document
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
            "BUILDFLAGS_NONE": 0,
            "BUILDFLAGS_EXTERNALRENDERER": 2,
            "COPYFLAGS_0": 0,
            "DESCFLAGS_SET_0": 0,
            "FILTER_EXR": 1016606,
            "FILTER_JPG": 1104,
            "FILTER_PNG": 1023671,
            "FILTER_TIF": 1100,
            "RDATA_FORMAT": 5033,
            "RDATA_FRAMEFROM": 5017,
            "RDATA_FRAMESEQUENCE": 5016,
            "RDATA_FRAMESEQUENCE_CURRENTFRAME": 1,
            "RDATA_FRAMETO": 5018,
            "RDATA_FRAMESTEP": 5019,
            "RDATA_MULTIPASS_FILENAME": 5206,
            "RDATA_MULTIPASS_SAVEFORMAT": 5203,
            "RDATA_MULTIPASS_SAVEIMAGE": 5200,
            "RDATA_PATH": 5041,
            "RDATA_RENDERENGINE": 5300,
            "RDATA_XRES": 5008,
            "RDATA_YRES": 5009,
            "COLORMODE_RGB": 4,
            "IMAGERESULT_OK": 0,
            "RDATA_SAVEIMAGE": 5040,
            "RENDERFLAGS_EXTERNAL": 1,
            "RENDERRESULT_FAILED": 11,
            "RENDERRESULT_OK": 0,
            "REDSHIFT_AOV_TYPE": 1000,
            "REDSHIFT_AOV_NAME": 1001,
            "REDSHIFT_AOV_ENABLED": 1002,
            "REDSHIFT_AOV_MULTIPASS_ENABLED": 1003,
            "REDSHIFT_AOV_FILE_ENABLED": 1004,
            "REDSHIFT_AOV_FILE_PATH": 1005,
            "REDSHIFT_AOV_FILE_EFFECTIVE_PATH": 6008,
            "REDSHIFT_AOV_TYPE_BEAUTY": 10,
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

    def _configured_render_data(self, name="Final", document=None):
        document = document or self.document
        render_data = self._render_data(name)
        render_data[self.c4d.RDATA_RENDERENGINE] = RS_RENDERER_ID
        render_data[self.c4d.RDATA_XRES] = 64.0
        render_data[self.c4d.RDATA_YRES] = 32.0
        render_data[self.c4d.RDATA_FORMAT] = self.c4d.FILTER_PNG
        render_data[self.c4d.RDATA_PATH] = "unchanged-source-path"
        render_data.video_post = FakeVideoPost()
        document.InsertRenderData(render_data)
        self.expected_render_data = render_data
        return render_data

    def _aov(self, path, *, effective_path=None):
        return FakeAov(
            {
                self.c4d.REDSHIFT_AOV_TYPE: 10,
                self.c4d.REDSHIFT_AOV_NAME: "Beauty AOV",
                self.c4d.REDSHIFT_AOV_ENABLED: True,
                self.c4d.REDSHIFT_AOV_MULTIPASS_ENABLED: True,
                self.c4d.REDSHIFT_AOV_FILE_ENABLED: True,
                self.c4d.REDSHIFT_AOV_FILE_PATH: path,
                self.c4d.REDSHIFT_AOV_FILE_EFFECTIVE_PATH: (
                    path if effective_path is None else effective_path
                ),
            }
        )

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
        self.assertEqual(
            created.video_post.set_parameter_calls, [(9001, 1.5, self.c4d.DESCFLAGS_SET_0)]
        )

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

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(ValueError, "parent directory"),
        ):
            render.handle_rs_configure_render(
                {
                    "name": "Bad Path",
                    "beauty_path": str(Path(temp_dir).resolve() / "missing-parent" / "x.png"),
                }
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

    def test_render_returns_beauty_and_aov_manifest_without_mutating_source_settings(self):
        source = self._configured_render_data()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "beauty.png")
            aov_path = os.path.join(temp_dir, "aov.png")
            raw_aov_path = os.path.join(temp_dir, "aov-prefix")
            self.aovs = [self._aov(raw_aov_path, effective_path=aov_path)]
            render = self._load()

            result = render.handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": output_path,
                    "force": True,
                }
            )

            self.assertGreater(result["beauty"]["size"], 0)
            self.assertEqual(result["beauty"]["path"], output_path)
            self.assertEqual(result["aovs"][0]["path"], aov_path)
            self.assertGreater(result["aovs"][0]["size"], 0)
            self.assertEqual(result["expected_missing"], [])
            self.assertFalse(os.path.exists(raw_aov_path))
            self.assertEqual(
                self.aovs[0].GetParameter(self.c4d.REDSHIFT_AOV_FILE_PATH), raw_aov_path
            )
        self.assertEqual(result["renderer"], {"id": RS_RENDERER_ID, "name": "Redshift"})
        self.assertEqual((result["width"], result["height"]), (64, 32))
        self.assertGreaterEqual(result["duration_ms"], 0)
        self.assertEqual(source[self.c4d.RDATA_PATH], "unchanged-source-path")
        self.assertIs(self.document.active_render_data, self.user_render_data)
        self.assertEqual(self.document.active_changes, [source, self.user_render_data])

    def test_render_guards_required_confirmation_and_output_paths_before_render(self):
        self._configured_render_data()
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "beauty.png")
            Path(output_path).write_bytes(b"existing")
            cases = [
                (
                    {"render_data_name": "Final", "output_path": output_path, "force": True},
                    "document_name",
                ),
                (
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": output_path,
                        "force": False,
                    },
                    "force",
                ),
                (
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": "relative.png",
                        "force": True,
                    },
                    "absolute",
                ),
                (
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": output_path,
                        "force": True,
                    },
                    "already exists",
                ),
            ]
            for params, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    render.handle_rs_render(params)

        self.assertEqual(self.render_calls, [])

    def test_render_rejects_render_data_renderer_and_video_post_preflight(self):
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:

            def request(name):
                return {
                    "document_name": "main",
                    "render_data_name": name,
                    "output_path": os.path.join(temp_dir, f"{name}.png"),
                    "force": True,
                }

            with self.assertRaisesRegex(ValueError, "not found"):
                render.handle_rs_render(request("Missing"))
            wrong = self._configured_render_data("Wrong")
            wrong[self.c4d.RDATA_RENDERENGINE] = 0
            with self.assertRaisesRegex(ValueError, "renderer"):
                render.handle_rs_render(request("Wrong"))
            no_post = self._configured_render_data("No Post")
            no_post.video_post = None
            with self.assertRaisesRegex(ValueError, "video post"):
                render.handle_rs_render(request("No Post"))
            self._configured_render_data("Dup")
            self._configured_render_data("Dup")
            with self.assertRaisesRegex(ValueError, "unique"):
                render.handle_rs_render(request("Dup"))

        self.assertEqual(self.render_calls, [])

    def test_render_validates_every_enabled_direct_aov_output_before_render(self):
        self._configured_render_data()
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:
            aov_path = os.path.join(temp_dir, "existing-aov.png")
            Path(aov_path).write_bytes(b"existing")
            invalid_paths = ["relative-aov.png", "", aov_path]
            for index, aov_path_value in enumerate(invalid_paths):
                self.aovs = [self._aov(aov_path_value)]
                with self.subTest(path=aov_path_value), self.assertRaises(ValueError):
                    render.handle_rs_render(
                        {
                            "document_name": "main",
                            "render_data_name": "Final",
                            "output_path": os.path.join(temp_dir, f"beauty-{index}.png"),
                            "force": True,
                        }
                    )

        self.assertEqual(self.render_calls, [])

    def test_render_rejects_existing_effective_path_before_render(self):
        self._configured_render_data()
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:
            effective_path = os.path.join(temp_dir, "aov.exr")
            Path(effective_path).write_bytes(b"existing AOV")
            self.aovs = [
                self._aov(os.path.join(temp_dir, "aov-prefix"), effective_path=effective_path)
            ]

            with self.assertRaisesRegex(ValueError, "already exists"):
                render.handle_rs_render(
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": os.path.join(temp_dir, "beauty.png"),
                        "force": True,
                        "overwrite": False,
                    }
                )

            self.assertEqual(Path(effective_path).read_bytes(), b"existing AOV")
        self.assertEqual(self.render_calls, [])

    def test_render_rejects_empty_effective_path_without_raw_path_fallback(self):
        self._configured_render_data()
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:
            self.aovs = [self._aov(os.path.join(temp_dir, "aov.png"), effective_path="")]

            with self.assertRaisesRegex(ValueError, "effective output path"):
                render.handle_rs_render(
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": os.path.join(temp_dir, "beauty.png"),
                        "force": True,
                    }
                )

        self.assertEqual(self.render_calls, [])

    def test_render_rejects_bitmap_allocation_before_render(self):
        self._configured_render_data()
        self.allocate_bitmap = False
        render = self._load()
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(RuntimeError, "bitmap"),
        ):
            render.handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": os.path.join(temp_dir, "beauty.png"),
                    "force": True,
                }
            )
        self.assertEqual(self.render_calls, [])
        self.assertIs(self.document.GetActiveRenderData(), self.user_render_data)

    def test_render_failure_restores_active_document_and_does_not_create_beauty(self):
        target_document = FakeRenderDocument("target")
        self.document.next = target_document
        self.document_state.items = [self.document, target_document]
        previous_render_data = self._render_data("Target Original")
        target_document.InsertRenderData(previous_render_data)
        target_document.active_render_data = previous_render_data
        target_render_data = self._configured_render_data(document=target_document)
        self.render_result = self.c4d.RENDERRESULT_FAILED
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "beauty.png")
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                render.handle_rs_render(
                    {
                        "document_name": "target",
                        "render_data_name": "Final",
                        "output_path": output_path,
                        "force": True,
                    }
                )
            self.assertFalse(os.path.exists(output_path))
        self.assertIs(self.document_state.active, self.document)
        self.assertIs(target_document.GetActiveRenderData(), previous_render_data)
        self.assertEqual(target_document.active_changes, [target_render_data, previous_render_data])

    def test_render_exception_restores_previous_active_render_data(self):
        target = self._configured_render_data()
        self.render_exception = RuntimeError("injected RenderDocument exception")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "beauty.png")
            with self.assertRaisesRegex(RuntimeError, "injected RenderDocument exception"):
                self._load().handle_rs_render(
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": output_path,
                        "force": True,
                    }
                )
            self.assertFalse(os.path.exists(output_path))

        self.assertIs(self.document.GetActiveRenderData(), self.user_render_data)
        self.assertEqual(self.document.active_changes, [target, self.user_render_data])

    def test_render_save_failure_and_missing_expected_aov_are_reported_truthfully(self):
        self._configured_render_data()
        render = self._load()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "beauty.png")
            self.save_result = 7
            with self.assertRaisesRegex(RuntimeError, "save"):
                render.handle_rs_render(
                    {
                        "document_name": "main",
                        "render_data_name": "Final",
                        "output_path": output_path,
                        "force": True,
                    }
                )
            self.assertFalse(os.path.exists(output_path))

            self.save_result = self.c4d.IMAGERESULT_OK
            aov_path = os.path.join(temp_dir, "missing-aov.png")
            self.aovs = [self._aov(aov_path)]
            self.write_aov_outputs = False
            result = render.handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": output_path,
                    "force": True,
                }
            )
            self.assertEqual(result["aovs"], [])
            self.assertEqual(result["expected_missing"][0]["path"], aov_path)
            self.assertTrue(result["warnings"])

    def test_explicit_frame_evaluates_and_restores_time_without_changing_source_settings(self):
        source = self._configured_render_data()
        source[self.c4d.RDATA_SAVEIMAGE] = True
        source[self.c4d.RDATA_MULTIPASS_SAVEIMAGE] = True
        source[self.c4d.RDATA_MULTIPASS_FILENAME] = "untouched-multipass-path"
        source[self.c4d.RDATA_FRAMEFROM] = FakeBaseTime(1, 30)
        source[self.c4d.RDATA_FRAMETO] = FakeBaseTime(90, 30)
        source[self.c4d.RDATA_FRAMESTEP] = 5
        source_values = dict(source.values)
        original_time = self.document.GetTime()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._load().handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": os.path.join(temp_dir, "frame_0012.png"),
                    "force": True,
                    "frame": 12,
                    "sequence_frame": True,
                }
            )
            self.assertEqual(sorted(os.listdir(temp_dir)), ["frame_0012.png"])

        settings = self.render_calls[0][1]
        self.assertEqual(result["frame"], 12)
        self.assertEqual(result["aovs"], [])
        self.assertEqual(self.render_times, [FakeBaseTime(12, 30)])
        self.assertEqual(settings[self.c4d.RDATA_FRAMEFROM], FakeBaseTime(12, 30))
        self.assertEqual(settings[self.c4d.RDATA_FRAMETO], FakeBaseTime(12, 30))
        self.assertEqual(settings[self.c4d.RDATA_FRAMESTEP], 1)
        self.assertEqual(
            settings[self.c4d.RDATA_FRAMESEQUENCE], self.c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        self.assertIs(settings[self.c4d.RDATA_SAVEIMAGE], False)
        self.assertIs(settings[self.c4d.RDATA_MULTIPASS_SAVEIMAGE], False)
        self.assertEqual(source.values, source_values)
        self.assertEqual(self.document.GetTime(), original_time)
        self.assertEqual(
            self.document.execute_calls,
            [
                (
                    FakeBaseTime(12, 30),
                    None,
                    True,
                    True,
                    True,
                    self.c4d.BUILDFLAGS_EXTERNALRENDERER,
                ),
                (original_time, None, True, True, True, self.c4d.BUILDFLAGS_NONE),
            ],
        )
        self.assertIs(self.document.GetActiveRenderData(), self.user_render_data)
        self.assertEqual(self.document.execute_render_data, [source, self.user_render_data])

    def test_explicit_frame_without_sequence_mode_keeps_aov_support(self):
        self._configured_render_data()
        with tempfile.TemporaryDirectory() as temp_dir:
            self.aovs = [self._aov(os.path.join(temp_dir, "depth.png"))]
            result = self._load().handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": os.path.join(temp_dir, "beauty.png"),
                    "force": True,
                    "frame": -2,
                }
            )
        self.assertEqual(result["frame"], -2)
        self.assertEqual(len(result["aovs"]), 1)
        self.assertEqual(self.document.GetTime(), FakeBaseTime(3, 30))

    def test_frame_and_sequence_input_validation_precedes_scene_changes(self):
        self._configured_render_data()
        cases = [
            ({"frame": True}, "frame must"),
            ({"frame": 1.5}, "frame must"),
            ({"frame": "2"}, "frame must"),
            ({"frame": None}, "frame must"),
            ({"sequence_frame": "true"}, "sequence_frame must"),
            ({"sequence_frame": True}, "requires frame"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            for extra, message in cases:
                with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, message):
                    self._load().handle_rs_render(
                        {
                            "document_name": "main",
                            "render_data_name": "Final",
                            "output_path": os.path.join(temp_dir, "frame.png"),
                            "force": True,
                            **extra,
                        }
                    )
        self.assertEqual(self.render_calls, [])
        self.assertEqual(self.document.active_changes, [])
        self.assertEqual(self.document.time_changes, [])

    def test_sequence_rejects_all_enabled_aovs_before_time_or_file_changes(self):
        self._configured_render_data()
        with tempfile.TemporaryDirectory() as temp_dir:
            for direct in (True, False):
                aov = self._aov(os.path.join(temp_dir, "aov.png"))
                aov.values[self.c4d.REDSHIFT_AOV_FILE_ENABLED] = direct
                self.aovs = [aov]
                with (
                    self.subTest(direct=direct),
                    self.assertRaisesRegex(ValueError, "no enabled AOVs"),
                ):
                    self._load().handle_rs_render(
                        {
                            "document_name": "main",
                            "render_data_name": "Final",
                            "output_path": os.path.join(temp_dir, "frame.png"),
                            "force": True,
                            "frame": 0,
                            "sequence_frame": True,
                        }
                    )
            self.assertEqual(os.listdir(temp_dir), [])
        self.assertEqual(self.render_calls, [])
        self.assertEqual(self.document.time_changes, [])
        self.assertIs(self.document.GetActiveRenderData(), self.user_render_data)

    def test_sequence_allows_disabled_aovs_without_writing_their_paths(self):
        self._configured_render_data()
        with tempfile.TemporaryDirectory() as temp_dir:
            aov = self._aov(os.path.join(temp_dir, "aov.png"))
            aov.values[self.c4d.REDSHIFT_AOV_ENABLED] = False
            self.aovs = [aov]
            result = self._load().handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": os.path.join(temp_dir, "frame.png"),
                    "force": True,
                    "frame": 0,
                    "sequence_frame": True,
                }
            )
            self.assertEqual(os.listdir(temp_dir), ["frame.png"])
        self.assertEqual(result["aovs"], [])

    def test_sequence_requires_png_filter_and_extension_before_changing_time(self):
        source = self._configured_render_data()
        with tempfile.TemporaryDirectory() as temp_dir:
            for output_format, filename in (
                (self.c4d.FILTER_EXR, "frame.png"),
                (self.c4d.FILTER_PNG, "frame.exr"),
            ):
                source[self.c4d.RDATA_FORMAT] = output_format
                with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "PNG"):
                    self._load().handle_rs_render(
                        {
                            "document_name": "main",
                            "render_data_name": "Final",
                            "output_path": os.path.join(temp_dir, filename),
                            "force": True,
                            "frame": 2,
                            "sequence_frame": True,
                        }
                    )
            self.assertEqual(os.listdir(temp_dir), [])
        self.assertEqual(self.render_calls, [])
        self.assertEqual(self.document.time_changes, [])
        self.assertIs(self.document.GetActiveRenderData(), self.user_render_data)

    def test_frame_failures_restore_time_evaluation_and_active_settings(self):
        source = self._configured_render_data()
        original_values = dict(source.values)
        with tempfile.TemporaryDirectory() as temp_dir:
            for failure in ("evaluate_false", "evaluate_exception", "render", "exception", "save"):
                self.render_result = self.c4d.RENDERRESULT_OK
                self.render_exception = None
                self.save_result = self.c4d.IMAGERESULT_OK
                self.document.execute_calls.clear()
                if failure == "evaluate_false":
                    self.document.execute_results = [False, True]
                elif failure == "evaluate_exception":
                    self.document.execute_results = [RuntimeError("evaluation failed"), True]
                elif failure == "render":
                    self.render_result = self.c4d.RENDERRESULT_FAILED
                elif failure == "exception":
                    self.render_exception = RuntimeError("injected render error")
                else:
                    self.save_result = 7
                with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                    self._load().handle_rs_render(
                        {
                            "document_name": "main",
                            "render_data_name": "Final",
                            "output_path": os.path.join(temp_dir, "frame.png"),
                            "force": True,
                            "frame": 8,
                            "sequence_frame": True,
                        }
                    )
                self.assertEqual(self.document.GetTime(), FakeBaseTime(3, 30))
                self.assertEqual(self.document.execute_calls[-1][0], FakeBaseTime(3, 30))
                self.assertEqual(len(self.document.execute_calls), 2)
                self.assertIs(self.document.GetActiveRenderData(), self.user_render_data)
                self.assertEqual(source.values, original_values)
            self.assertEqual(os.listdir(temp_dir), [])

    def test_restore_evaluation_failure_still_restores_active_render_data_and_document(self):
        target = FakeRenderDocument("target")
        self.document.next = target
        self.document_state.items = [self.document, target]
        previous_render_data = self._render_data("Previous")
        target.InsertRenderData(previous_render_data)
        target.active_render_data = previous_render_data
        self._configured_render_data(document=target)
        target.execute_results = [True, False]
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(RuntimeError, "failed to evaluate"),
        ):
            self._load().handle_rs_render(
                {
                    "document_name": "target",
                    "render_data_name": "Final",
                    "output_path": os.path.join(temp_dir, "frame.png"),
                    "force": True,
                    "frame": 2,
                    "sequence_frame": True,
                }
            )
        self.assertEqual(target.GetTime(), FakeBaseTime(3, 30))
        self.assertIs(target.GetActiveRenderData(), previous_render_data)
        self.assertIs(self.document_state.active, self.document)

    def test_legacy_render_does_not_change_or_evaluate_document_time(self):
        self._configured_render_data()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._load().handle_rs_render(
                {
                    "document_name": "main",
                    "render_data_name": "Final",
                    "output_path": os.path.join(temp_dir, "beauty.png"),
                    "force": True,
                }
            )
        self.assertNotIn("frame", result)
        self.assertEqual(self.document.time_changes, [])
        self.assertEqual(self.document.execute_calls, [])


if __name__ == "__main__":
    unittest.main()
