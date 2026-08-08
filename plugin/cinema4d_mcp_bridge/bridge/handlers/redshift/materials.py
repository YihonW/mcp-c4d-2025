"""Create or reuse Redshift node materials without mutating existing graphs."""

from __future__ import annotations

import c4d
import maxon

from ._helpers import RS_NODE_SPACE_ID, document_scope, require_redshift


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
                start_undo()
            except Exception:
                pass
            else:
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
