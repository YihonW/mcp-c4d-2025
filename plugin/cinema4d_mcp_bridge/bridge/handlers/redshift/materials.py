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
_RS_COLORSPACE_RAW = "RS_INPUT_COLORSPACE_RAW"


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
                element=None if created else matches[0],
                nodeSpaceId=maxon.Id(RS_NODE_SPACE_ID),
                createEmpty=False,
                name=name,
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
        assets = repository.FindAssets(maxon.AssetTypes.NodeTemplate().GetId())
        available = {str(asset.GetId()) for asset in assets}
    except Exception as exc:
        raise RuntimeError(f"Redshift node-template repository unavailable: {exc}") from exc
    missing = [name for name, asset_id in NODE_ASSETS.items() if asset_id not in available]
    if missing:
        raise RuntimeError(f"required Redshift PBR node assets unavailable: {', '.join(missing)}")


def _graph_nodes(graph) -> list[dict[str, object]]:
    from ..node_materials import _node_asset_id

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
            asset_id = _node_asset_id(node)
        except Exception:
            asset_id = ""
        nodes.append({"id": node_id, "asset_id": asset_id, "node": node})
        try:
            for child in node.GetChildren():
                visit(child)
        except Exception:
            pass

    with contextlib.suppress(Exception):
        for child in graph.GetRoot().GetChildren():
            visit(child)
    return nodes


def _unique_graph_node(
    nodes: list[dict[str, object]], asset_id: str, name: str
) -> dict[str, object]:
    matches = [node for node in nodes if node.get("asset_id") == asset_id]
    if not matches:
        raise ValueError(f"{name} node not found in Redshift graph")
    if len(matches) != 1:
        raise ValueError(f"{name} node is ambiguous in Redshift graph")
    return matches[0]


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _texture_input(value: object, channel: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{channel} texture must be an object")
    path = require_texture_path(value.get("path"))
    color_space = value.get("color_space")
    if color_space is None:
        color_space = "color" if channel == "base_color" else "raw"
    if not isinstance(color_space, str) or not color_space:
        raise ValueError(f"{channel}.color_space must be a non-empty string")
    return path, color_space


def _runtime_port(node, port_id: str, direction: str):
    from ..node_materials import _node_asset_id

    asset_id = _node_asset_id(node)
    if not asset_id or not port_id.startswith("#~."):
        raise RuntimeError(
            f"required runtime port unavailable: {port_id!r}; refusing graph mutation"
        )
    parts = port_id.removeprefix("#~.").split("/")
    root_id = f"{asset_id}.{parts.pop(0)}"
    ports = node.GetInputs() if direction == "in" else node.GetOutputs()
    # C4D 2025.3.2 can reject Id -> InternedId conversion here; use string IDs.
    port = ports.FindChild(root_id)
    try:
        valid = port is not None and bool(port.IsValid())
    except Exception:
        valid = False
    for part in parts:
        if not valid:
            break
        port = port.FindChild(part)
        try:
            valid = port is not None and bool(port.IsValid())
        except Exception:
            valid = False
    if not valid:
        raise RuntimeError(
            f"required runtime port unavailable: {port_id!r} ({direction}); refusing graph mutation"
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
    try:
        children = list(graph.GetRoot().GetChildren())
    except Exception:
        return False
    return all(callable(getattr(child, "Remove", None)) for child in children)


def _clear_graph(graph) -> None:
    try:
        children = list(graph.GetRoot().GetChildren())
    except Exception as exc:
        raise RuntimeError("replace_graph is unsupported: graph cannot be cleared safely") from exc
    for child in children:
        remove = getattr(child, "Remove", None)
        if not callable(remove):
            raise RuntimeError("replace_graph is unsupported: graph cannot be cleared safely")
        remove()


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
        with contextlib.suppress(Exception):
            end_undo()
        return False, None, None
    return True, end_undo, undo_type


def _texture_description(node_id: str, path: str, color_space: str) -> dict[str, object]:
    texture_color_space = {
        "color": "",
        "raw": _RS_COLORSPACE_RAW,
    }.get(color_space, color_space)
    return {
        "$type": NODE_ASSETS["texture"],
        "$id": node_id,
        _TEXTURE_PATH_PORT: path,
        _TEXTURE_COLOR_SPACE_PORT: texture_color_space,
    }


def _node_map(graph) -> dict[str, object]:
    return {str(node["id"]): node["node"] for node in _graph_nodes(graph)}


def _coerce_pbr_port_value(value: object) -> object:
    """Reuse the generic node-material coercion only on the raw-asset fallback path."""
    from ..node_materials import _coerce_port_value

    return _coerce_port_value(value)


def _set_or_connect(node_map: dict[str, object], node_id: str, port_id: str, value: object) -> None:
    target = _runtime_port(node_map[node_id], port_id, "in")
    if not isinstance(value, dict) or "$id" not in value:
        port_value = _coerce_pbr_port_value(value)
        target.SetPortValue(port_value)
        if port_id == _TEXTURE_COLOR_SPACE_PORT:
            # Validate the authored attribute written by SetPortValue, not derived "value".
            read_value = target.GetValue("net.maxon.description.data.base.defaultvalue")
            if read_value != port_value:
                raise RuntimeError(
                    "texture color_space readback mismatch: "
                    f"expected={port_value!r} ({type(port_value).__name__}), "
                    f"actual={read_value!r} ({type(read_value).__name__}); refusing graph mutation"
                )
        return
    source = node_map.get(str(value["$id"]))
    if source is None:
        raise RuntimeError(f"connection source node not found: {value['$id']!r}")
    source_port_id = value.get("$output")
    if not isinstance(source_port_id, str) or not source_port_id.startswith("#~."):
        raise RuntimeError("connection source output must be an exact runtime port ID")
    source_port = _runtime_port(source, source_port_id, "out")
    source_port.Connect(target)


def _apply_pbr_lowlevel(graph, description: tuple[dict[str, object], ...]) -> None:
    """Apply raw Redshift asset ids within the caller's already-open transaction."""
    node_map = _node_map(graph)
    for operation in description:
        asset_id = operation.get("$type")
        if not isinstance(asset_id, str):
            continue
        node_id = str(operation["$id"])
        node = graph.AddChild(maxon.Id(node_id), maxon.Id(asset_id), maxon.DataDictionary())
        node_map[node_id] = node
        for port_id, value in operation.items():
            if port_id not in {"$type", "$id"}:
                _set_or_connect(node_map, node_id, port_id, value)
    for operation in description:
        query = operation.get("$query")
        if not isinstance(query, dict) or not isinstance(query.get("$id"), str):
            continue
        node_id = query["$id"]
        for port_id, value in operation.items():
            if port_id != "$query":
                _set_or_connect(node_map, node_id, port_id, value)


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
        node_material = material.GetNodeMaterialReference()
        graph = node_material.GetGraph(maxon.Id(RS_NODE_SPACE_ID)) if node_material else None
        if not graph:
            raise RuntimeError("Redshift material graph is unavailable")
        nodes = _graph_nodes(graph)

        snapshot = None
        restore = None
        if replace_graph:
            if not _can_clear_graph(graph):
                raise RuntimeError("replace_graph is unsupported: graph cannot be cleared safely")
            snapshot, restore = _snapshot_graph(graph)
            standard_id = "standard"
            output_id = "output"
        else:
            standard = _unique_graph_node(nodes, NODE_ASSETS["standard"], "Standard Material")
            output = _unique_graph_node(nodes, NODE_ASSETS["output"], "Output")
            standard_id = str(standard["id"])
            output_id = str(output["id"])
            standard_node = standard["node"]
            output_node = output["node"]
            for channel, port_id in _STANDARD_PORTS.items():
                if channel in params:
                    _runtime_port(standard_node, port_id, "in")
            if "normal" in params:
                _runtime_port(standard_node, "#~.bump_input", "in")
            if "displacement" in params:
                _runtime_port(output_node, "#~.displacement", "in")

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
                        "#~.surface": {"$id": standard_id, "$output": "#~.outcolor"},
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
                path, color_space = _texture_input(value, channel)
                texture_id = f"{channel}_texture"
                operations.append(_texture_description(texture_id, path, color_space))
                operations.append(
                    {
                        "$query": {"$id": standard_id},
                        _STANDARD_PORTS[channel]: {
                            "$id": texture_id,
                            "$output": "#~.outcolor",
                        },
                    }
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
                        _STANDARD_PORTS[channel]: tuple(
                            _number(component, "base_color") for component in value
                        ),
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
            path, color_space = _texture_input(normal.get("texture"), "normal")
            strength = _number(normal.get("strength", 1.0), "normal.strength")
            operations.extend(
                [
                    _texture_description("normal_texture", path, color_space),
                    {
                        "$type": NODE_ASSETS["bump"],
                        "$id": "normal_bump",
                        "#~.input": {"$id": "normal_texture", "$output": "#~.outcolor"},
                        "#~.strength": strength,
                    },
                    {
                        "$query": {"$id": standard_id},
                        "#~.bump_input": {"$id": "normal_bump", "$output": "#~.out"},
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
            path, color_space = _texture_input(displacement.get("texture"), "displacement")
            scale = _number(displacement.get("scale", 1.0), "displacement.scale")
            operations.extend(
                [
                    _texture_description("displacement_texture", path, color_space),
                    {
                        "$type": NODE_ASSETS["displacement"],
                        "$id": "displacement_node",
                        "#~.input": {
                            "$id": "displacement_texture",
                            "$output": "#~.outcolor",
                        },
                        "#~.scale": scale,
                    },
                    {
                        "$query": {"$id": output_id},
                        "#~.displacement": {
                            "$id": "displacement_node",
                            "$output": "#~.out",
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
                if any("$type" in operation for operation in operation_list):
                    _apply_pbr_lowlevel(graph, operation_list)
                else:
                    maxon.GraphDescription.ApplyDescription(
                        graph, list(operation_list), nodeSpace=maxon.Id(RS_NODE_SPACE_ID)
                    )
                transaction.Commit()
        except Exception as exc:
            if not replace_graph:
                raise
            rollback = "unavailable"
            if replace_graph and restore is not None:
                try:
                    restore(snapshot)
                except Exception as restore_exc:
                    raise RuntimeError(f"{exc}; rollback=partial: {restore_exc}") from exc
                rollback = "succeeded"
            raise RuntimeError(f"{exc}; rollback={rollback}") from exc
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
