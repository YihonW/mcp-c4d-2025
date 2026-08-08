"""Create or reuse Redshift node materials without mutating existing graphs."""

from __future__ import annotations

import contextlib
import math

import c4d
import maxon

from ._helpers import RS_NODE_SPACE_ID, document_scope, require_redshift, require_texture_path

NODE_ASSETS = {
    "output": "com.redshift3d.redshift4c4d.node.output",
    "standard": "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "texture": "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
    "bump": "com.redshift3d.redshift4c4d.nodes.core.bumpmap",
    "displacement": "com.redshift3d.redshift4c4d.nodes.core.displacement",
}

_STANDARD_PORTS = {
    "base_color": "#~.base_color",
    "metalness": "#~.metalness",
    "roughness": "#~.refl_roughness",
}
_TEXTURE_PATH_PORT = "#~.tex0/path"
_TEXTURE_COLOR_SPACE_PORT = "#~.tex0/colorspace"


def _materials_named(document, name: str) -> list[object]:
    matches: list[object] = []
    material = document.GetFirstMaterial()
    while material is not None:
        if material.GetName() == name:
            matches.append(material)
        material = material.GetNext()
    return matches


def handle_rs_create_material(params: dict[str, object]) -> dict[str, object]:
    """Create a Redshift node material, or reuse one unambiguous exact-name match."""
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a non-empty string")
    update_if_exists = params.get("update_if_exists", False)
    if not isinstance(update_if_exists, bool):
        raise ValueError("update_if_exists must be a boolean")

    require_redshift("materials")
    with document_scope(params.get("document_name"), required=True) as document:
        matches = _materials_named(document, name)
        if len(matches) > 1:
            raise ValueError(f"material name is ambiguous: {name!r}")
        if matches and not update_if_exists:
            raise ValueError(f"material already exists: {name!r}")

        created = not matches
        material_or_name = name if created else matches[0]
        undo_type = getattr(c4d, "UNDOTYPE_NEW", None)
        start_undo = getattr(document, "StartUndo", None)
        end_undo = getattr(document, "EndUndo", None)
        add_undo = getattr(document, "AddUndo", None)
        undo_started = False
        undo_supported = False
        if (
            created
            and undo_type is not None
            and all(callable(method) for method in (start_undo, end_undo, add_undo))
        ):
            try:
                start_result = start_undo()
            except Exception:
                pass
            else:
                if start_result is not False:
                    undo_started = True
                    undo_supported = True

        try:
            graph = maxon.GraphDescription.CreateGraph(
                material_or_name,
                nodeSpaceId=maxon.Id(RS_NODE_SPACE_ID),
                createEmpty=False,
            )
            if graph is None:
                raise RuntimeError("failed to create or obtain Redshift material graph")

            if created:
                matches = _materials_named(document, name)
                if len(matches) != 1:
                    raise RuntimeError(f"created material name is not unique: {name!r}")
                material = matches[0]
                if undo_started:
                    add_undo(undo_type, material)
            else:
                material = matches[0]

            return {
                "document_name": document.GetDocumentName(),
                "handle": {"kind": "material", "name": material.GetName()},
                "node_space_id": RS_NODE_SPACE_ID,
                "created": created,
                "undo_supported": undo_supported,
            }
        finally:
            if undo_started:
                end_undo()


def _require_pbr_node_assets() -> None:
    try:
        repository = maxon.AssetInterface.GetUserPrefsRepository()
        assets = repository.FindAssets(maxon.AssetTypes.NodeTemplate)
        available = {str(asset.GetId()) for asset in assets}
    except Exception as exc:
        raise RuntimeError(f"Redshift node-template repository unavailable: {exc}") from exc
    missing = [name for name, asset_id in NODE_ASSETS.items() if asset_id not in available]
    if missing:
        raise RuntimeError(f"required Redshift PBR node assets unavailable: {', '.join(missing)}")


def _graph_nodes(graph) -> list[dict[str, object]]:
    if isinstance(getattr(graph, "nodes", None), list):
        return [dict(node) for node in graph.nodes if isinstance(node, dict)]

    nodes: list[dict[str, object]] = []
    seen: set[str] = set()

    def visit(node) -> None:
        try:
            node_id = str(node.GetId())
        except Exception:
            return
        if not node_id or node_id in seen:
            return
        seen.add(node_id)
        try:
            asset_id = str(node.GetValue("net.maxon.node.attribute.assetid") or "")
        except Exception:
            asset_id = ""
        nodes.append({"id": node_id, "asset_id": asset_id})
        try:
            for child in node.GetChildren():
                visit(child)
        except Exception:
            pass

    with contextlib.suppress(Exception):
        visit(graph.GetRoot())
    return nodes


def _unique_graph_node(nodes: list[dict[str, object]], asset_id: str, name: str) -> str:
    matches = [str(node["id"]) for node in nodes if node.get("asset_id") == asset_id]
    if not matches:
        raise ValueError(f"{name} node not found in Redshift graph")
    if len(matches) != 1:
        raise ValueError(f"{name} node is ambiguous in Redshift graph")
    return matches[0]


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _texture_input(value: object, channel: str, graph) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{channel} texture must be an object")
    path = require_texture_path(value.get("path"))
    color_space = value.get("color_space")
    if color_space is None:
        color_space = "color" if channel == "base_color" else "raw"
    if not isinstance(color_space, str) or not color_space:
        raise ValueError(f"{channel}.color_space must be a non-empty string")
    validator = getattr(graph, "ValidateColorSpace", None)
    if callable(validator) and not validator(color_space):
        raise ValueError(f"unknown color space: {color_space}")
    return path, color_space


def _runtime_port(graph, asset_id: str, role: str) -> str:
    resolver = getattr(graph, "ResolvePort", None)
    port = resolver(asset_id, role) if callable(resolver) else None
    if not isinstance(port, str) or not port.startswith("#~."):
        raise RuntimeError(
            f"required runtime port unavailable for {asset_id!r} ({role}); refusing graph mutation"
        )
    return port


def _snapshot_graph(graph):
    clone = getattr(graph, "Clone", None)
    restore = getattr(graph, "Restore", None)
    if not callable(clone) or not callable(restore):
        raise RuntimeError("replace_graph requires a reliable graph snapshot and restore API")
    try:
        return clone(), restore
    except Exception as exc:
        raise RuntimeError(
            "replace_graph requires a reliable graph snapshot and restore API"
        ) from exc


def _can_clear_graph(graph) -> bool:
    return isinstance(getattr(graph, "nodes", None), list) or callable(
        getattr(graph, "RemoveNode", None)
    )


def _clear_graph(graph) -> None:
    if isinstance(getattr(graph, "nodes", None), list):
        graph.nodes.clear()
        return
    remove_node = getattr(graph, "RemoveNode", None)
    if not callable(remove_node):
        raise RuntimeError("replace_graph is unsupported: graph cannot be cleared safely")
    root = graph.GetRoot()
    children = list(root.GetChildren())
    for child in children:
        remove_node(child)


def _start_material_undo(document, material) -> tuple[bool, object | None, object | None]:
    undo_type = getattr(c4d, "UNDOTYPE_CHANGE", getattr(c4d, "UNDOTYPE_NEW", None))
    start_undo = getattr(document, "StartUndo", None)
    end_undo = getattr(document, "EndUndo", None)
    add_undo = getattr(document, "AddUndo", None)
    if undo_type is None or not all(
        callable(method) for method in (start_undo, end_undo, add_undo)
    ):
        return False, None, None
    try:
        if start_undo() is False:
            return False, None, None
        add_undo(undo_type, material)
    except Exception:
        return False, None, None
    return True, end_undo, undo_type


def _texture_description(node_id: str, path: str, color_space: str) -> dict[str, object]:
    return {
        "$type": NODE_ASSETS["texture"],
        "$id": node_id,
        _TEXTURE_PATH_PORT: path,
        _TEXTURE_COLOR_SPACE_PORT: color_space,
    }


def handle_rs_set_material_pbr(params: dict[str, object]) -> dict[str, object]:
    """Set supplied PBR channels after fully validating the Redshift graph plan."""
    replace_graph = params.get("replace_graph", False)
    if not isinstance(replace_graph, bool):
        raise ValueError("replace_graph must be a boolean")
    document_name = params.get("document_name")
    if replace_graph and not isinstance(document_name, str):
        raise ValueError("replace_graph requires document_name")
    handle = params.get("material")
    if not isinstance(handle, dict) or handle.get("kind") != "material":
        raise ValueError("material must be a material handle")
    material_name = handle.get("name")
    if not isinstance(material_name, str) or not material_name:
        raise ValueError("material.name must be a non-empty string")

    supplied = [
        channel
        for channel in ("base_color", "metalness", "roughness", "normal", "displacement")
        if channel in params
    ]
    if not supplied:
        raise ValueError("at least one PBR channel is required")

    require_redshift("materials")
    _require_pbr_node_assets()
    with document_scope(document_name, required=True) as document:
        matches = _materials_named(document, material_name)
        if not matches:
            raise ValueError(f"material not found: {material_name!r}")
        if len(matches) != 1:
            raise ValueError(f"material name is ambiguous: {material_name!r}")
        material = matches[0]
        graph = maxon.GraphDescription.GetGraph(
            material, nodeSpaceId=maxon.Id(RS_NODE_SPACE_ID), createEmpty=False
        )
        if graph is None:
            raise RuntimeError("Redshift material graph is unavailable")
        nodes = _graph_nodes(graph)
        standard_id = _unique_graph_node(nodes, NODE_ASSETS["standard"], "Standard Material")
        output_id = _unique_graph_node(nodes, NODE_ASSETS["output"], "Output")

        snapshot = None
        restore = None
        output_surface = None
        standard_surface = None
        if replace_graph:
            if not _can_clear_graph(graph):
                raise RuntimeError("replace_graph is unsupported: graph cannot be cleared safely")
            snapshot, restore = _snapshot_graph(graph)
            output_surface = _runtime_port(graph, NODE_ASSETS["output"], "surface_input")
            standard_surface = _runtime_port(graph, NODE_ASSETS["standard"], "surface_output")
            standard_id = "standard"
            output_id = "output"

        operations: list[dict[str, object]] = []
        created_nodes: list[dict[str, str]] = []
        color_spaces: dict[str, str] = {}

        if replace_graph:
            operations.extend(
                [
                    {"$type": NODE_ASSETS["output"], "$id": output_id},
                    {"$type": NODE_ASSETS["standard"], "$id": standard_id},
                    {
                        "$query": {"$id": output_id},
                        output_surface: {"$id": standard_id, standard_surface: True},
                    },
                ]
            )
            created_nodes.extend(
                [
                    {"id": output_id, "asset_id": NODE_ASSETS["output"]},
                    {"id": standard_id, "asset_id": NODE_ASSETS["standard"]},
                ]
            )

        for channel in ("base_color", "metalness", "roughness"):
            if channel not in params:
                continue
            value = params[channel]
            if isinstance(value, dict):
                path, color_space = _texture_input(value, channel, graph)
                texture_id = f"{channel}_texture"
                operations.append(_texture_description(texture_id, path, color_space))
                operations.append(
                    {"$query": {"$id": standard_id}, _STANDARD_PORTS[channel]: {"$id": texture_id}}
                )
                created_nodes.append({"id": texture_id, "asset_id": NODE_ASSETS["texture"]})
                color_spaces[channel] = color_space
            elif channel == "base_color":
                if (
                    not isinstance(value, (list, tuple))
                    or len(value) != 3
                    or any(isinstance(component, bool) for component in value)
                ):
                    raise ValueError("base_color must be an RGB triple or texture")
                operations.append(
                    {
                        "$query": {"$id": standard_id},
                        _STANDARD_PORTS[channel]: [
                            _number(component, "base_color") for component in value
                        ],
                    }
                )
            else:
                operations.append(
                    {
                        "$query": {"$id": standard_id},
                        _STANDARD_PORTS[channel]: _number(value, channel),
                    }
                )

        if "normal" in params:
            normal = params["normal"]
            if not isinstance(normal, dict):
                raise ValueError("normal must be an object")
            path, color_space = _texture_input(normal.get("texture"), "normal", graph)
            strength = _number(normal.get("strength", 1.0), "normal.strength")
            normal_input = _runtime_port(graph, NODE_ASSETS["bump"], "input")
            normal_output = _runtime_port(graph, NODE_ASSETS["bump"], "output")
            normal_strength = _runtime_port(graph, NODE_ASSETS["bump"], "strength")
            standard_normal = _runtime_port(graph, NODE_ASSETS["standard"], "normal_input")
            operations.extend(
                [
                    _texture_description("normal_texture", path, color_space),
                    {
                        "$type": NODE_ASSETS["bump"],
                        "$id": "normal_bump",
                        normal_input: {"$id": "normal_texture"},
                        normal_strength: strength,
                    },
                    {
                        "$query": {"$id": standard_id},
                        standard_normal: {"$id": "normal_bump", normal_output: True},
                    },
                ]
            )
            created_nodes.extend(
                [
                    {"id": "normal_texture", "asset_id": NODE_ASSETS["texture"]},
                    {"id": "normal_bump", "asset_id": NODE_ASSETS["bump"]},
                ]
            )
            color_spaces["normal"] = color_space

        if "displacement" in params:
            displacement = params["displacement"]
            if not isinstance(displacement, dict):
                raise ValueError("displacement must be an object")
            path, color_space = _texture_input(displacement.get("texture"), "displacement", graph)
            scale = _number(displacement.get("scale", 1.0), "displacement.scale")
            displacement_input = _runtime_port(graph, NODE_ASSETS["displacement"], "input")
            displacement_output = _runtime_port(graph, NODE_ASSETS["displacement"], "output")
            displacement_scale = _runtime_port(graph, NODE_ASSETS["displacement"], "scale")
            output_displacement = _runtime_port(graph, NODE_ASSETS["output"], "displacement_input")
            operations.extend(
                [
                    _texture_description("displacement_texture", path, color_space),
                    {
                        "$type": NODE_ASSETS["displacement"],
                        "$id": "displacement_node",
                        displacement_input: {"$id": "displacement_texture"},
                        displacement_scale: scale,
                    },
                    {
                        "$query": {"$id": output_id},
                        output_displacement: {
                            "$id": "displacement_node",
                            displacement_output: True,
                        },
                    },
                ]
            )
            created_nodes.extend(
                [
                    {"id": "displacement_texture", "asset_id": NODE_ASSETS["texture"]},
                    {"id": "displacement_node", "asset_id": NODE_ASSETS["displacement"]},
                ]
            )
            color_spaces["displacement"] = color_space

        operation_list = tuple(operations)
        undo_started, end_undo, _undo_type = _start_material_undo(document, material)
        try:
            with graph.BeginTransaction() as transaction:
                if replace_graph:
                    _clear_graph(graph)
                maxon.GraphDescription.ApplyDescription(
                    graph, list(operation_list), nodeSpace=maxon.Id(RS_NODE_SPACE_ID)
                )
                transaction.Commit()
        except Exception:
            if replace_graph and restore is not None:
                with contextlib.suppress(Exception):
                    restore(snapshot)
            raise
        finally:
            if undo_started and callable(end_undo):
                end_undo()

        return {
            "document_name": document.GetDocumentName(),
            "material": {"kind": "material", "name": material.GetName()},
            "updated_channels": supplied,
            "created_nodes": created_nodes,
            "color_spaces": color_spaces,
            "replaced_graph": replace_graph,
            "undo_supported": undo_started,
            "rollback": "not_needed",
        }
