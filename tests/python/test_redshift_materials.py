from __future__ import annotations

import contextlib
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from redshift_fakes import FakeId, make_c4d_runtime, make_maxon_runtime, make_redshift_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugin" / "cinema4d_mcp_bridge"
RS_NODE_SPACE_ID = "com.redshift3d.redshift4c4d.class.nodespace"
MATERIAL_ASSETS = (
    "com.redshift3d.redshift4c4d.node.output",
    "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
    "com.redshift3d.redshift4c4d.nodes.core.bumpmap",
    "com.redshift3d.redshift4c4d.nodes.core.displacement",
)

NODE_ASSETS = {
    "output": "com.redshift3d.redshift4c4d.node.output",
    "standard": "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "texture": "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
    "bump": "com.redshift3d.redshift4c4d.nodes.core.bumpmap",
    "displacement": "com.redshift3d.redshift4c4d.nodes.core.displacement",
}


class FakeMaterial:
    def __init__(self, name: str):
        self.name = name
        self.next: FakeMaterial | None = None
        self.graph = None

    def GetName(self):
        return self.name

    def GetNext(self):
        return self.next

    def GetNodeMaterialReference(self):
        return self

    def GetGraph(self, _node_space):
        return self.graph


PORTS = {
    NODE_ASSETS["output"]: (["surface", "displacement"], []),
    NODE_ASSETS["standard"]: (
        ["base_color", "metalness", "refl_roughness", "bump_input"],
        ["outcolor"],
    ),
    NODE_ASSETS["texture"]: (["tex0"], ["outcolor"]),
    NODE_ASSETS["bump"]: (["input", "strength"], ["out"]),
    NODE_ASSETS["displacement"]: (["input", "scale"], ["out"]),
}


class FakePort:
    def __init__(self, port_id, allowed_values=None, children=None):
        self.port_id = port_id
        self.allowed_values = allowed_values
        self.value = None
        self.connections = []
        self.children = children or {}
        self.silent_ignore_invalid_value = False

    def IsValid(self):
        return True

    def GetId(self):
        return self.port_id

    def GetValue(self, attribute):
        if attribute == "net.maxon.node.attribute.enumvalues":
            return self.allowed_values
        return None

    def FindChild(self, name):
        if not isinstance(name, str):
            raise TypeError(
                "unable to convert builtins.NativePyData to @net.maxon.datatype.internedid"
            )
        return self.children.get(name, FakeInvalidPort())

    def SetPortValue(self, value):
        if self.allowed_values is not None and value not in self.allowed_values:
            if self.silent_ignore_invalid_value:
                return
            raise ValueError(f"unknown color space: {value}")
        self.value = value

    def GetPortValue(self):
        return self.value

    def Connect(self, target):
        self.connections.append(target)


class FakeInvalidPort:
    def IsValid(self):
        return False


class FakePortList:
    def __init__(self, ports):
        self.ports = ports

    def FindChild(self, name):
        if not isinstance(name, str):
            raise TypeError(
                "unable to convert builtins.NativePyData to @net.maxon.datatype.internedid"
            )
        return self.ports.get(name, FakeInvalidPort())

    def GetChildren(self):
        return iter(self.ports.values())


class FakeSdkAssetIdAndVersion:
    """Maxon's indexable pair is not a Python tuple/list."""

    def __init__(self, asset_id, version=""):
        self.values = (FakeId(asset_id), FakeId(version))

    def __getitem__(self, index):
        return self.values[index]

    def __str__(self):
        return f"({self.values[0]},{self.values[1]})"


class FakeGraphNode:
    def __init__(self, node_id, asset_id=None):
        self.node_id = node_id
        self.asset_id = asset_id
        inputs, outputs = PORTS.get(asset_id, ([], []))
        self.inputs = {
            f"{asset_id}.{port_id}": FakePort(f"{asset_id}.{port_id}") for port_id in inputs
        }
        if asset_id == NODE_ASSETS["texture"]:
            self.inputs[f"{asset_id}.tex0"] = FakePort(
                f"{asset_id}.tex0",
                children={
                    "path": FakePort("path"),
                    "colorspace": FakePort("colorspace", {"", "RS_INPUT_COLORSPACE_RAW", "acescg"}),
                },
            )
        self.outputs = {
            f"{asset_id}.{port_id}": FakePort(f"{asset_id}.{port_id}") for port_id in outputs
        }
        self.children = []
        self.parent = None

    def IsValid(self):
        return True

    def GetId(self):
        return self.node_id

    def GetValue(self, attribute):
        if attribute == "net.maxon.node.attribute.assetid":
            return FakeSdkAssetIdAndVersion(self.asset_id or "")
        return None

    def GetInputs(self):
        return FakePortList(self.inputs)

    def GetOutputs(self):
        return FakePortList(self.outputs)

    def GetChildren(self):
        return iter(self.children)

    def Remove(self):
        self.parent.children.remove(self)


class FakeGraph:
    def __init__(self, material):
        self.material = material
        self.root = FakeGraphNode("")
        self.root.children = [
            FakeGraphNode("output", NODE_ASSETS["output"]),
            FakeGraphNode("standard", NODE_ASSETS["standard"]),
        ]
        for node in self.root.children:
            node.parent = self.root
        self.transactions = []
        self.clone_supported = True
        self.restore_raises = False
        self.silent_ignore_color_space = False
        self.raise_on_add_child = False

    @property
    def nodes(self):
        return [{"id": node.GetId(), "asset_id": node.asset_id} for node in self.root.children]

    def GetRoot(self):
        return self.root

    def AddChild(self, node_id, asset_id, _data):
        if self.raise_on_add_child:
            raise RuntimeError("injected low-level graph failure")
        node = FakeGraphNode(str(node_id), str(asset_id))
        if node.asset_id == NODE_ASSETS["texture"]:
            node.GetInputs().FindChild(f"{node.asset_id}.tex0").FindChild(
                "colorspace"
            ).silent_ignore_invalid_value = self.silent_ignore_color_space
        node.parent = self.root
        self.root.children.append(node)
        return node

    def BeginTransaction(self):
        graph = self

        class Transaction:
            def __enter__(self):
                self.snapshot = graph.Clone()
                self.committed = False
                graph.transactions.append("begin")
                return self

            def Commit(self):
                self.committed = True
                graph.transactions.append("commit")

            def __exit__(self, exc_type, _exc, _traceback):
                if exc_type is not None or not self.committed:
                    graph._restore(self.snapshot)
                    graph.transactions.append("rollback")

        return Transaction()

    def Clone(self):
        if not self.clone_supported:
            raise RuntimeError("clone unavailable")
        return [(node.GetId(), node.asset_id) for node in self.root.children]

    def Restore(self, snapshot):
        if self.restore_raises:
            raise RuntimeError("injected restore failure")
        self._restore(snapshot)

    def _restore(self, snapshot):
        self.root.children = [FakeGraphNode(node_id, asset_id) for node_id, asset_id in snapshot]
        for node in self.root.children:
            node.parent = self.root


class FakeMaterialDocument:
    def __init__(self, document, materials=()):
        self.document = document
        self.materials = list(materials)
        self.undo_calls = []
        self.undo_events = []
        self.raise_on_add_undo = False
        self._link_materials()

    def _link_materials(self):
        for current, following in zip(self.materials, self.materials[1:], strict=False):
            current.next = following
        if self.materials:
            self.materials[-1].next = None

    def GetFirstMaterial(self):
        return self.materials[0] if self.materials else None

    def AddUndo(self, undo_type, material):
        self.undo_calls.append((undo_type, material))
        self.undo_events.append(("add", undo_type, material))
        if self.raise_on_add_undo:
            raise RuntimeError("injected AddUndo failure")

    def StartUndo(self):
        self.undo_events.append("start")

    def EndUndo(self):
        self.undo_events.append("end")

    def add_material(self, material):
        self.materials.append(material)
        self._link_materials()


class FakeGraphDescription:
    def __init__(self, document_state, document_map):
        self.document_state = document_state
        self.document_map = document_map
        self.calls = []
        self.active_document = None

    def CreateGraph(self, element=None, *, nodeSpaceId, createEmpty, name=""):
        if element is not None and not isinstance(element, FakeMaterial):
            raise TypeError("element must be BaseList2D or None; pass material name by keyword")
        material_or_name = element if element is not None else name
        self.active_document = self.document_state.active
        self.calls.append((material_or_name, str(nodeSpaceId), createEmpty))
        if isinstance(material_or_name, str):
            self.document_map[self.document_state.active].add_material(
                FakeMaterial(material_or_name)
            )
        return object()


class FakePbrGraphDescription(FakeGraphDescription):
    def __init__(self, document_state, document_map):
        super().__init__(document_state, document_map)
        self.graphs = {}
        self.graph_mutation_calls = []
        self.raise_on_apply = False
        self.reject_raw_assets = True
        self.partial_write_on_apply = False

    def graph_for(self, material):
        graph = self.graphs.setdefault(material, FakeGraph(material))
        material.graph = graph
        return graph

    def GetGraph(self, material, *, nodeSpaceId, createEmpty=False):
        self.calls.append(("get", material, str(nodeSpaceId), createEmpty))
        return self.graph_for(material)

    def ApplyDescription(self, graph, description, *, nodeSpace):
        self.graph_mutation_calls.append((graph, description, str(nodeSpace)))
        if self.partial_write_on_apply:
            graph.AddChild("orphan", NODE_ASSETS["texture"], {})
            raise RuntimeError("node type reference is not associated with any IDs")
        if self.raise_on_apply:
            raise RuntimeError("injected graph transaction failure")
        if self.reject_raw_assets and any("$type" in operation for operation in description):
            raise RuntimeError("node type reference is not associated with any IDs")
        return {}


class RedshiftMaterialsTest(unittest.TestCase):
    def setUp(self):
        self.c4d, self.documents, self.document_state, _ = make_c4d_runtime(
            document_names=["main", "user"]
        )
        self.c4d.UNDOTYPE_NEW = 100
        self.maxon, _ = make_maxon_runtime(MATERIAL_ASSETS)
        self.maxon.DataDictionary = dict
        self.maxon.Vector = lambda x, y, z: [x, y, z]
        self.redshift = make_redshift_runtime()
        self.document_map = {
            document: FakeMaterialDocument(document) for document in self.document_state.items
        }
        for document, material_document in self.document_map.items():
            document.GetFirstMaterial = material_document.GetFirstMaterial
            document.AddUndo = material_document.AddUndo
            document.StartUndo = material_document.StartUndo
            document.EndUndo = material_document.EndUndo
        self.user_document = self.document_state.items[1]
        self.graph_description = FakePbrGraphDescription(self.document_state, self.document_map)
        self.maxon.GraphDescription = self.graph_description
        self.maxon.NodeSpaceIdentifiers = types.SimpleNamespace(RedshiftMaterial=RS_NODE_SPACE_ID)
        bridge = types.ModuleType("bridge")
        bridge.__path__ = [str(PLUGIN_ROOT / "bridge")]
        handlers = types.ModuleType("bridge.handlers")
        handlers.__path__ = [str(PLUGIN_ROOT / "bridge" / "handlers")]
        parent_helpers = types.ModuleType("bridge.handlers._helpers")

        def require_abs_path(value, **_kwargs):
            if value == "C:/missing/normal.png":
                raise ValueError(f"file not found: {value}")
            return str(value)

        parent_helpers._require_abs_path = require_abs_path
        parent_helpers._require_writable_path = lambda value: str(value)
        parent_helpers._resolve_handle = lambda value: value
        self.modules = {
            "c4d": self.c4d,
            "c4d.documents": self.documents,
            "maxon": self.maxon,
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

    @property
    def active_document(self):
        return self.document_state.active

    @property
    def graph_create_calls(self):
        return len(self.graph_description.calls)

    @property
    def graph_mutation_calls(self):
        return self.graph_description.graph_mutation_calls

    def handle_rs_create_material(self, params):
        return importlib.import_module(
            "bridge.handlers.redshift.materials"
        ).handle_rs_create_material(params)

    def handle_rs_set_material_pbr(self, params):
        return importlib.import_module(
            "bridge.handlers.redshift.materials"
        ).handle_rs_set_material_pbr(params)

    def add_pbr_material(self, name="RS_Mat"):
        material = FakeMaterial(name)
        self.document_map[self.user_document].add_material(material)
        self.graph_description.graph_for(material)
        return material

    def test_missing_graph_is_rejected_without_creating_one(self):
        material = FakeMaterial("Classic")
        self.document_map[self.user_document].add_material(material)
        with self.assertRaisesRegex(RuntimeError, "material graph is unavailable"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "Classic"},
                    "roughness": 0.35,
                }
            )
        self.assertIsNone(material.graph)
        self.assertEqual(self.graph_description.calls, [])

    def test_graph_readers_decode_sdk_asset_id_and_version(self):
        graph = FakeGraph(FakeMaterial("RS_Mat"))
        redshift_materials = importlib.import_module("bridge.handlers.redshift.materials")
        node_materials = importlib.import_module("bridge.handlers.node_materials")
        for read_nodes in (redshift_materials._graph_nodes, node_materials._collect_nodes):
            with self.subTest(reader=read_nodes.__name__):
                nodes = {entry["id"]: entry["asset_id"] for entry in read_nodes(graph)}
                self.assertEqual(nodes["standard"], NODE_ASSETS["standard"])
                self.assertEqual(nodes["output"], NODE_ASSETS["output"])

    def test_asset_id_reader_accepts_native_pair_without_builtin_tuple_check(self):
        materials = importlib.import_module("bridge.handlers.node_materials")
        for value, expected in (
            (FakeSdkAssetIdAndVersion(NODE_ASSETS["standard"], "1.0"), NODE_ASSETS["standard"]),
            ((FakeId(NODE_ASSETS["output"]), FakeId("")), NODE_ASSETS["output"]),
            (FakeSdkAssetIdAndVersion(""), ""),
            (None, ""),
        ):
            with self.subTest(value=str(value)):
                node = types.SimpleNamespace(GetValue=lambda _attribute, value=value: value)
                self.assertEqual(materials._node_asset_id(node), expected)

    def test_runtime_ports_use_asset_id_without_version(self):
        materials = importlib.import_module("bridge.handlers.redshift.materials")
        for asset_id, port_id, direction in (
            (NODE_ASSETS["standard"], "#~.refl_roughness", "in"),
            (NODE_ASSETS["texture"], "#~.tex0/path", "in"),
            (NODE_ASSETS["texture"], "#~.tex0/colorspace", "in"),
            (NODE_ASSETS["texture"], "#~.outcolor", "out"),
        ):
            with self.subTest(asset_id=asset_id, port_id=port_id):
                node = FakeGraphNode("instance", asset_id)
                port = materials._runtime_port(node, port_id, direction)
                self.assertTrue(port.IsValid())

    def test_creates_a_material_in_the_requested_document_and_records_undo(self):
        result = self.handle_rs_create_material({"document_name": "user", "name": "RS_Mat"})

        self.assertEqual(result["handle"], {"kind": "material", "name": "RS_Mat"})
        self.assertEqual(result["node_space_id"], RS_NODE_SPACE_ID)
        self.assertTrue(result["created"])
        self.assertTrue(result["undo_supported"])
        self.assertIs(self.graph_description.active_document, self.user_document)
        self.assertIs(self.active_document, self.document_state.items[0])
        self.assertEqual(
            self.graph_description.calls,
            [("RS_Mat", RS_NODE_SPACE_ID, False)],
        )
        self.assertEqual(
            self.document_map[self.user_document].undo_calls,
            [(self.c4d.UNDOTYPE_NEW, self.document_map[self.user_document].materials[0])],
        )
        self.assertEqual(
            self.document_map[self.user_document].undo_events,
            [
                "start",
                (
                    "add",
                    self.c4d.UNDOTYPE_NEW,
                    self.document_map[self.user_document].materials[0],
                ),
                "end",
            ],
        )

    def test_marks_undo_unsupported_without_a_complete_or_startable_undo_surface(self):
        del self.user_document.EndUndo

        incomplete = self.handle_rs_create_material({"document_name": "user", "name": "NoEnd"})

        self.assertFalse(incomplete["undo_supported"])
        self.assertEqual(self.document_map[self.user_document].undo_calls, [])
        self.assertEqual(self.document_map[self.user_document].undo_events, [])

        self.user_document.EndUndo = self.document_map[self.user_document].EndUndo

        def fail_start_undo():
            self.document_map[self.user_document].undo_events.append("start")
            raise RuntimeError("undo unavailable")

        self.user_document.StartUndo = fail_start_undo
        failed_start = self.handle_rs_create_material(
            {"document_name": "user", "name": "StartFails"}
        )

        self.assertFalse(failed_start["undo_supported"])
        self.assertEqual(self.document_map[self.user_document].undo_calls, [])
        self.assertEqual(self.document_map[self.user_document].undo_events, ["start"])

        self.document_map[self.user_document].undo_calls.clear()
        self.document_map[self.user_document].undo_events.clear()
        self.user_document.StartUndo = lambda: False
        false_start = self.handle_rs_create_material(
            {"document_name": "user", "name": "StartReturnsFalse"}
        )

        self.assertFalse(false_start["undo_supported"])
        self.assertEqual(self.document_map[self.user_document].undo_calls, [])
        self.assertEqual(self.document_map[self.user_document].undo_events, [])

    def test_reuses_exactly_one_same_name_material_when_requested(self):
        material = FakeMaterial("RS_Mat")
        self.document_map[self.user_document].add_material(material)

        result = self.handle_rs_create_material(
            {"document_name": "user", "name": "RS_Mat", "update_if_exists": True}
        )

        self.assertFalse(result["created"])
        self.assertEqual(self.graph_description.calls, [(material, RS_NODE_SPACE_ID, False)])
        self.assertEqual(self.document_map[self.user_document].materials, [material])

    def test_rejects_default_duplicate_and_ambiguous_update_before_graph_creation(self):
        self.document_map[self.user_document].add_material(FakeMaterial("RS_Mat"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.handle_rs_create_material({"document_name": "user", "name": "RS_Mat"})
        self.assertEqual(self.graph_create_calls, 0)

        self.document_map[self.user_document].add_material(FakeMaterial("Dup"))
        self.document_map[self.user_document].add_material(FakeMaterial("Dup"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.handle_rs_create_material(
                {"document_name": "user", "name": "Dup", "update_if_exists": True}
            )
        self.assertEqual(self.graph_create_calls, 0)

    def test_rejects_missing_material_capability_before_any_write(self):
        repository = self.maxon.AssetInterface.GetUserPrefsRepository()
        repository.assets = [
            asset for asset in repository.assets if str(asset.GetId()) != NODE_ASSETS["standard"]
        ]

        with self.assertRaisesRegex(RuntimeError, "Redshift capability unavailable"):
            self.handle_rs_create_material({"document_name": "user", "name": "RS_Mat"})

        self.assertEqual(self.graph_create_calls, 0)
        self.assertEqual(self.document_map[self.user_document].materials, [])

    def test_sets_scalar_and_color_channels_without_creating_texture_nodes(self):
        self.add_pbr_material()

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "base_color": [0.1, 0.2, 0.3],
                "metalness": 0.2,
                "roughness": 0.35,
            }
        )

        self.assertEqual(result["document_name"], "user")
        self.assertEqual(result["material"], {"kind": "material", "name": "RS_Mat"})
        self.assertEqual(result["updated_channels"], ["base_color", "metalness", "roughness"])
        self.assertEqual(result["created_nodes"], [])
        self.assertEqual(result["color_spaces"], {})
        self.assertFalse(result["replaced_graph"])
        self.assertTrue(result["undo_supported"])
        self.assertEqual(result["rollback"], "not_needed")
        self.assertEqual(len(self.graph_mutation_calls), 1)
        _, description, node_space = self.graph_mutation_calls[0]
        self.assertEqual(node_space, RS_NODE_SPACE_ID)
        self.assertEqual(
            description,
            [
                {"$query": {"$id": "standard"}, "#~.base_color": [0.1, 0.2, 0.3]},
                {"$query": {"$id": "standard"}, "#~.metalness": 0.2},
                {"$query": {"$id": "standard"}, "#~.refl_roughness": 0.35},
            ],
        )

    def test_routes_all_texture_channels_with_exact_assets_and_color_policy(self):
        self.add_pbr_material()

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "base_color": {"path": "C:/textures/base.exr"},
                "metalness": {"path": "C:/textures/metal.png", "color_space": "acescg"},
                "roughness": {"path": "C:/textures/rough.png"},
                "normal": {"texture": {"path": "C:/textures/normal.png"}, "strength": 0.75},
                "displacement": {
                    "texture": {"path": "C:/textures/displace.exr"},
                    "scale": 0.2,
                },
            }
        )

        self.assertEqual(
            result["updated_channels"],
            ["base_color", "metalness", "roughness", "normal", "displacement"],
        )
        self.assertEqual(result["color_spaces"]["base_color"], "color")
        self.assertEqual(result["color_spaces"]["metalness"], "acescg")
        self.assertEqual(result["color_spaces"]["roughness"], "raw")
        self.assertEqual(result["color_spaces"]["normal"], "raw")
        self.assertEqual(result["color_spaces"]["displacement"], "raw")
        self.assertEqual(
            [node["asset_id"] for node in result["created_nodes"]],
            [
                NODE_ASSETS["texture"],
                NODE_ASSETS["texture"],
                NODE_ASSETS["texture"],
                NODE_ASSETS["texture"],
                NODE_ASSETS["bump"],
                NODE_ASSETS["texture"],
                NODE_ASSETS["displacement"],
            ],
        )
        self.assertEqual(self.graph_mutation_calls, [])
        graph = self.graph_description.graph_for(self.document_map[self.user_document].materials[0])
        nodes = {node.GetId(): node for node in graph.root.GetChildren()}
        texture_output = (
            nodes["base_color_texture"].GetOutputs().FindChild(f"{NODE_ASSETS['texture']}.outcolor")
        )
        self.assertEqual(
            [port.GetId() for port in texture_output.connections],
            [f"{NODE_ASSETS['standard']}.base_color"],
        )
        expected_color_spaces = {
            "base_color_texture": "",
            "metalness_texture": "acescg",
            "roughness_texture": "RS_INPUT_COLORSPACE_RAW",
            "normal_texture": "RS_INPUT_COLORSPACE_RAW",
            "displacement_texture": "RS_INPUT_COLORSPACE_RAW",
        }
        for node_id, expected_value in expected_color_spaces.items():
            color_space = (
                nodes[node_id]
                .GetInputs()
                .FindChild(f"{NODE_ASSETS['texture']}.tex0")
                .FindChild("colorspace")
            )
            self.assertEqual(color_space.GetPortValue(), expected_value)

    def test_updates_only_the_supplied_channel(self):
        self.add_pbr_material()

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "roughness": 0.35,
            }
        )

        self.assertEqual(result["updated_channels"], ["roughness"])
        _, description, _ = self.graph_mutation_calls[0]
        self.assertEqual(
            description,
            [{"$query": {"$id": "standard"}, "#~.refl_roughness": 0.35}],
        )

    def test_rejects_absent_or_ambiguous_material_before_any_graph_mutation(self):
        with self.assertRaisesRegex(ValueError, "material.*not found"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "roughness": 0.35,
                }
            )
        self.assertEqual(self.graph_mutation_calls, [])

        self.add_pbr_material("RS_Mat")
        self.add_pbr_material("RS_Mat")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "roughness": 0.35,
                }
            )
        self.assertEqual(self.graph_mutation_calls, [])

    def test_rejects_invalid_texture_and_missing_node_asset_before_any_graph_mutation(self):
        self.add_pbr_material()
        self.documents.SetActiveDocument(self.user_document)
        with self.assertRaisesRegex(ValueError, "file not found"):
            self.handle_rs_set_material_pbr(
                {
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "normal": {"texture": {"path": "C:/missing/normal.png"}},
                }
            )
        self.assertEqual(self.graph_mutation_calls, [])

        repository = self.maxon.AssetInterface.GetUserPrefsRepository()
        repository.assets = [
            asset for asset in repository.assets if str(asset.GetId()) != NODE_ASSETS["bump"]
        ]
        with self.assertRaisesRegex(RuntimeError, "bump"):
            self.handle_rs_set_material_pbr(
                {
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "normal": {"texture": {"path": "C:/textures/normal.png"}},
                }
            )
        self.assertEqual(self.graph_mutation_calls, [])

    def test_reports_transaction_failure_without_committing_the_graph(self):
        material = self.add_pbr_material()
        graph = self.graph_description.graph_for(material)
        self.graph_description.raise_on_apply = True

        with self.assertRaisesRegex(RuntimeError, "injected graph transaction failure"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "roughness": 0.35,
                }
            )

        self.assertEqual(graph.transactions, ["begin", "rollback"])

    def test_requires_document_and_reliable_snapshot_before_replacing_a_graph(self):
        self.add_pbr_material()
        with self.assertRaisesRegex(ValueError, "replace_graph.*document_name"):
            self.handle_rs_set_material_pbr(
                {
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "replace_graph": True,
                    "roughness": 0.35,
                }
            )
        self.assertEqual(self.graph_mutation_calls, [])

        material = self.document_map[self.user_document].materials[0]
        self.graph_description.graph_for(material).clone_supported = False
        with self.assertRaisesRegex(RuntimeError, "replace_graph.*snapshot"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "replace_graph": True,
                    "roughness": 0.35,
                }
            )
        self.assertEqual(self.graph_mutation_calls, [])

    def test_replaces_a_snapshotted_graph_with_one_output_to_standard_connection(self):
        material = self.add_pbr_material()

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "replace_graph": True,
                "roughness": 0.35,
            }
        )

        self.assertTrue(result["replaced_graph"])
        self.assertEqual(result["rollback"], "not_needed")
        self.assertEqual(self.graph_mutation_calls, [])
        graph = self.graph_description.graph_for(material)
        nodes = {node.GetId(): node for node in graph.root.GetChildren()}
        standard_output = (
            nodes["standard"].GetOutputs().FindChild(f"{NODE_ASSETS['standard']}.outcolor")
        )
        self.assertEqual(
            [port.GetId() for port in standard_output.connections],
            [f"{NODE_ASSETS['output']}.surface"],
        )
        self.assertEqual(
            self.graph_description.graph_for(material).nodes[:2],
            [
                {"id": "output", "asset_id": NODE_ASSETS["output"]},
                {"id": "standard", "asset_id": NODE_ASSETS["standard"]},
            ],
        )

    def test_replace_rebuilds_without_requiring_legacy_output_or_standard_nodes(self):
        material = self.add_pbr_material()
        self.graph_description.graph_for(material).root.children.clear()

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "replace_graph": True,
                "roughness": 0.35,
            }
        )

        self.assertTrue(result["replaced_graph"])
        self.assertEqual(
            self.graph_description.graph_for(material).nodes[:2],
            [
                {"id": "output", "asset_id": NODE_ASSETS["output"]},
                {"id": "standard", "asset_id": NODE_ASSETS["standard"]},
            ],
        )

    def test_replace_apply_failure_restores_snapshot_and_reports_rollback_status(self):
        material = self.add_pbr_material()
        graph = self.graph_description.graph_for(material)
        before = graph.Clone()
        graph.raise_on_add_child = True

        with self.assertRaisesRegex(
            RuntimeError, "injected low-level graph failure; rollback=succeeded"
        ):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "replace_graph": True,
                    "roughness": 0.35,
                }
            )

        self.assertEqual(graph.Clone(), before)

    def test_replace_restore_failure_reports_partial_rollback(self):
        material = self.add_pbr_material()
        graph = self.graph_description.graph_for(material)
        graph.raise_on_add_child = True
        graph.restore_raises = True

        with self.assertRaisesRegex(
            RuntimeError,
            "injected low-level graph failure; rollback=partial.*injected restore failure",
        ):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "replace_graph": True,
                    "roughness": 0.35,
                }
            )

    def test_ends_undo_group_when_add_undo_fails(self):
        self.add_pbr_material()
        document = self.document_map[self.user_document]
        document.raise_on_add_undo = True

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "roughness": 0.35,
            }
        )

        self.assertFalse(result["undo_supported"])
        self.assertEqual(
            document.undo_events[:3], ["start", ("add", 100, document.materials[0]), "end"]
        )

    def test_rejects_unknown_texture_color_space_without_committing_graph_changes(self):
        material = self.add_pbr_material()
        graph = self.graph_description.graph_for(material)
        before = graph.Clone()

        with self.assertRaisesRegex(ValueError, "unknown color space"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "base_color": {"path": "C:/textures/base.exr", "color_space": "unknown"},
                }
            )

        self.assertEqual(graph.Clone(), before)
        self.assertEqual(graph.transactions[-2:], ["begin", "rollback"])

    def test_raw_asset_operations_skip_apply_description_to_prevent_partial_fallback_writes(self):
        material = self.add_pbr_material()
        graph = self.graph_description.graph_for(material)
        self.graph_description.partial_write_on_apply = True

        result = self.handle_rs_set_material_pbr(
            {
                "document_name": "user",
                "material": {"kind": "material", "name": "RS_Mat"},
                "base_color": {"path": "C:/textures/base.exr"},
            }
        )

        self.assertEqual(result["created_nodes"][0]["id"], "base_color_texture")
        self.assertEqual(self.graph_mutation_calls, [])
        self.assertNotIn("orphan", [node["id"] for node in graph.nodes])

    def test_rejects_silently_ignored_color_space_and_rolls_back_the_transaction(self):
        material = self.add_pbr_material()
        graph = self.graph_description.graph_for(material)
        graph.silent_ignore_color_space = True
        before = graph.Clone()

        with self.assertRaisesRegex(RuntimeError, "color_space.*readback"):
            self.handle_rs_set_material_pbr(
                {
                    "document_name": "user",
                    "material": {"kind": "material", "name": "RS_Mat"},
                    "base_color": {"path": "C:/textures/base.exr", "color_space": "unknown"},
                }
            )

        self.assertEqual(graph.Clone(), before)
        self.assertEqual(graph.transactions[-2:], ["begin", "rollback"])


if __name__ == "__main__":
    unittest.main()
