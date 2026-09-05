# Redshift Control Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live-verified, document-safe Redshift production path for Cinema 4D 2025.3.2: capability discovery, node materials and PBR textures, Redshift lights and camera, AOV CRUD, RenderData configuration, and guarded Beauty+AOV rendering.

**Architecture:** Keep the MCP boundary typed and thin in TypeScript, and implement all Cinema 4D/Redshift behavior in a lazily loaded Python handler package that runs on the existing main-thread dispatcher. Every mutation first performs the shared Redshift probe and complete input validation, scopes changes to a uniquely named document when requested or required, uses undo/node transactions where available, snapshots non-transactional AOV/RenderData state, and restores the prior active document in `finally`. Existing generic graph and parameter tools remain the low-level layer; the new `rs_*` tools are the production-oriented layer.

**Tech Stack:** TypeScript 6, Zod 4, MCP TypeScript SDK, Vitest 4, Cinema 4D 2025.3.2 Python 3.11 API, Maxon Nodes/GraphDescription API, Redshift Python module, Python `unittest`, Ruff, oxlint, oxfmt.

## Global Constraints

- Implement only the user-approved specification in `docs/superpowers/specs/2026-08-08-redshift-control-design.md`; the roadmap after the first milestone is out of scope.
- Target only Windows x64, Cinema 4D raw version `2025302`, bridge `0.4.0`, and renderer ID `1036219`. Do not add compatibility claims for another release or OS.
- Do not import `redshift` at module import time. The base bridge must still start when Redshift or an optional Redshift symbol is absent.
- Do not enable or depend on `exec_python`; the strict gate requires it to remain disabled.
- Do not fall back to Standard, Viewport, another light type, another AOV type, or a nearby parameter when an exact Redshift feature is unavailable.
- Ordinary create/update calls accept an optional `document_name`; `replace_graph`, `rs_clear_aovs`, and `rs_render` require a unique `document_name` plus their explicit confirmation flag.
- Validate names, duplicate resolution, every texture path, every output path, every enum/raw ID, and every required SDK symbol before the first write.
- A client timeout never means that a synchronous render was cancelled. The response and error text must not make that claim.
- Preserve all unrelated user changes and never stage them. In particular, do not touch the basketball plan/spec files if they appear modified again during execution.
- Do not restart or close the user's Cinema 4D process. Installation is allowed only after a passing dry-run; tell the user when a manual Cinema 4D restart is required.
- Use RED -> GREEN for every task. A RED run is valid only when it fails for the missing behavior named in that task, not for an import, syntax, fixture, or environment mistake.
- After each GREEN, run the focused Python and TypeScript suites before committing. Run the complete offline and live release gates only in Task 9.

### Stable public response shapes

All handlers return JSON-serializable records with these common conventions:

```python
ROLLBACK_STATES = ("not_needed", "succeeded", "partial", "unavailable")

material_handle = {"kind": "material", "name": "RS_Material"}
object_handle = {"kind": "object", "path": "/RS_Key", "name": "RS_Key"}
render_data_handle = {"kind": "render_data", "name": "RS_64x64"}
```

Unsupported read-side capability entries use `{"supported": False, "reason": "specific reason"}`. Mutating tools raise a specific `RuntimeError` or `ValueError` before mutation. Mutation responses include `document_name`, canonical handle/record fields, `undo_supported`, and `rollback` when rollback is applicable.

---

## Task 1: Shared Redshift capability and safety boundary

**Files:**

- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/_helpers.py`
- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/capabilities.py`
- Create: `tests/python/redshift_fakes.py`
- Create: `tests/python/test_redshift_capabilities.py`
- Create: `src/tools/rs-get-capabilities.ts`
- Create: `tests/unit/redshift-tools.test.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/__init__.py`
- Modify: `src/tools/define-tool.ts`
- Modify: `src/tools/index.ts`
- Modify: `scripts/generate-tools-doc.mjs`

**Interfaces produced:**

```python
RS_RENDERER_ID = 1036219
RS_POST_EFFECT_ID = 1040189
RS_NODE_SPACE_ID = "com.redshift3d.redshift4c4d.class.nodespace"
```

The helper module exports these exact call contracts: `load_redshift() -> tuple[object | None,
str | None]`, `probe_redshift() -> dict[str, object]`, `require_redshift(*features: str) ->
dict[str, object]`, `resolve_document(document_name: str | None, *, required: bool = False)`,
`document_scope(document_name: str | None, *, required: bool = False)`,
`assert_active_document(target) -> None`, `require_texture_path(value: object) -> str`, and
`require_output_path(value: object, *, overwrite: bool) -> str`.

```ts
export const rsGetCapabilitiesTool: ToolSpec<{}>;
```

**Interfaces consumed:** `c4d.GetC4DVersion`, `c4d.plugins.FindPlugin`, `c4d.documents.GetFirstDocument`, `GetActiveDocument`, `SetActiveDocument`, optional `maxon`, optional `redshift`, and the existing `C4DClient.request`/`defineTool` conventions.

- [ ] Add `tests/python/redshift_fakes.py` with reusable fake document chaining, active-document tracking, fake plugin lookup, fake `maxon.Id`/node-template repository, and a configurable fake `redshift` module. Keep the fixture behavioral: record writes and symbol calls instead of reproducing Cinema 4D internals.

- [ ] Add `tests/python/test_redshift_capabilities.py` covering all of the following cases:

```python
def test_missing_redshift_module_is_reported_without_import_failure(self):
    result = self.capabilities.handle_rs_get_capabilities({})
    self.assertFalse(result["module"]["supported"])
    self.assertIn("redshift module", result["module"]["reason"])

def test_complete_runtime_reports_renderer_nodes_aovs_lights_camera_and_render(self):
    result = self.capabilities.handle_rs_get_capabilities({})
    self.assertEqual(result["renderer"], {"supported": True, "id": 1036219})
    self.assertEqual(result["node_space"]["id"], RS_NODE_SPACE_ID)
    self.assertGreaterEqual(result["node_space"]["node_template_count"], 1)
    self.assertTrue(result["aov_api"]["supported"])
    self.assertTrue(result["lights"]["types"]["area"]["supported"])
    self.assertTrue(result["camera"]["supported"])
    self.assertTrue(result["render"]["supported"])

def test_missing_optional_symbol_disables_only_its_feature(self):
    del self.redshift.RendererSetAOVs
    result = self.capabilities.handle_rs_get_capabilities({})
    self.assertFalse(result["aov_api"]["supported"])
    self.assertTrue(result["materials"]["supported"])
```

Also test that `resolve_document` rejects zero/duplicate names before `SetActiveDocument`, and that `document_scope` restores the prior document after success and after an exception.

- [ ] Run the focused Python suite and confirm RED because the `bridge.handlers.redshift` package does not exist:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_capabilities.py" -v
```

Expected: import/module failure naming `bridge.handlers.redshift`, with the fake-module fixture itself loading successfully.

- [ ] Implement `redshift/_helpers.py` with lazy import and document scoping. The lazy loader must use `importlib.import_module("redshift")` inside the function, cache neither failure nor module globally, and convert import errors to a reason string. Use one exact-match open-document scan and always restore only if the previous document is still open:

```python
@contextlib.contextmanager
def document_scope(document_name: str | None, *, required: bool = False):
    previous = documents.GetActiveDocument()
    target = resolve_document(document_name, required=required)
    try:
        if target is not previous:
            documents.SetActiveDocument(target)
        assert_active_document(target)
        yield target
        assert_active_document(target)
    finally:
        if previous is not None and _is_open_document(previous):
            if documents.GetActiveDocument() != previous:
                documents.SetActiveDocument(previous)
        c4d.EventAdd()
```

`require_texture_path` must call the existing `_require_abs_path` with `must_exist=True` and also reject directories. `require_output_path` must call `_require_writable_path`, verify that the parent is writable, reject an existing destination unless `overwrite=True`, and must not create a probe file.

- [ ] Implement `probe_redshift()` as one shared snapshot used by the public capability handler and every later mutator. Probe these exact symbols without mutating scene state:

```python
required_aov_symbols = (
    "FindAddVideoPost",
    "RendererGetAOVs",
    "RendererSetAOVs",
    "RSAOV",
    "VPrsrenderer",
)
required_material_assets = (
    "com.redshift3d.redshift4c4d.node.output",
    "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
)
```

Return top-level keys `renderer`, `post_effect`, `module`, `node_space`, `materials`, `aov_api`, `lights`, `camera`, and `render`. Each feature contains `supported`; unavailable entries include `reason`. `lights.types` reports each of `area`, `dome`, `sun`, `point`, and `spot` independently from the corresponding `c4d.REDSHIFT_LIGHT_TYPE_*` symbol.

- [ ] Implement `capabilities.py` and package registration:

```python
def handle_rs_get_capabilities(_params: dict[str, Any]) -> dict[str, Any]:
    snapshot = probe_redshift()
    return {
        "c4d_version": int(c4d.GetC4DVersion()),
        "renderer_id": RS_RENDERER_ID,
        "node_space_id": RS_NODE_SPACE_ID,
        **snapshot,
    }
```

`redshift/__init__.py` exports a `REDSHIFT_HANDLERS` dictionary. The root handler module imports that dictionary and calls `HANDLERS.update(REDSHIFT_HANDLERS)` after constructing its existing table. No root import may import the actual `redshift` module.

- [ ] Add the TypeScript tool and registration test. Add `"redshift"` to `ToolGroup` and this group metadata to the doc generator:

```js
{
  id: "redshift",
  title: "Redshift",
  blurb: "Validated high-level Redshift materials, lights, cameras, AOVs, and renders.",
}
```

The tool implementation is intentionally thin:

```ts
export const rsGetCapabilitiesTool = defineTool({
  name: "rs_get_capabilities",
  group: "redshift",
  title: "Get Redshift Capabilities",
  description:
    "Report exact Redshift renderer, module, node-space, AOV, light, camera, and render support without mutating the scene.",
  inputShape: {},
  async handler(_args, client) {
    return textResult(await client.request("rs_get_capabilities", {}, 10_000));
  },
});
```

In `tests/unit/redshift-tools.test.ts`, assert the tool is present in `ALL_TOOLS`, has group `redshift`, and sends the exact command/timeout. Do not assert the intermediate registry length; that would make unrelated future tool additions break this behavior test.

- [ ] Run focused GREEN tests:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_capabilities.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

Expected: all pass; importing root `HANDLERS` with no `redshift` module remains successful.

- [ ] Commit only Task 1 files:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift plugin/cinema4d_mcp_bridge/bridge/handlers/__init__.py tests/python/redshift_fakes.py tests/python/test_redshift_capabilities.py src/tools/rs-get-capabilities.ts src/tools/define-tool.ts src/tools/index.ts scripts/generate-tools-doc.mjs tests/unit/redshift-tools.test.ts
git commit -m "feat: add Redshift capability boundary"
```

---

## Task 2: Create or reuse a Redshift node material safely

**Files:**

- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/materials.py`
- Create: `tests/python/test_redshift_materials.py`
- Create: `src/tools/rs-create-material.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interface produced:**

```ts
rs_create_material({
  document_name?: string;
  name: string;
  update_if_exists?: boolean;
}): Promise<{
  document_name: string;
  handle: { kind: "material"; name: string };
  node_space_id: string;
  created: boolean;
  undo_supported: boolean;
}>;
```

**Interfaces consumed:** `require_redshift("materials")`, `document_scope`, `maxon.GraphDescription.CreateGraph`, `maxon.NodeSpaceIdentifiers.RedshiftMaterial`, and active-document material iteration.

- [ ] Add Python tests for create, unique update, duplicate rejection, and failure-before-write. The key assertions are:

```python
self.assertEqual(result["handle"], {"kind": "material", "name": "RS_Mat"})
self.assertEqual(result["node_space_id"], RS_NODE_SPACE_ID)
self.assertTrue(result["created"])
self.assertIs(self.active_document, self.user_document)

with self.assertRaisesRegex(ValueError, "already exists"):
    handle_rs_create_material({"name": "RS_Mat"})
self.assertEqual(self.graph_create_calls, 0)

with self.assertRaisesRegex(ValueError, "ambiguous"):
    handle_rs_create_material({"name": "Dup", "update_if_exists": True})
```

- [ ] Add TS schema tests requiring a non-empty trimmed `name`, accepting optional `document_name` and `update_if_exists`, and forwarding with a 30-second timeout. Run both focused suites and confirm RED because the handler/tool is missing.

```powershell
python -m unittest discover -s tests/python -p "test_redshift_materials.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
```

- [ ] Implement `handle_rs_create_material`. Resolve all same-name materials before calling GraphDescription. Default duplicate behavior is failure; `update_if_exists:true` may reuse exactly one material. Create or obtain the graph without clearing it:

```python
graph = maxon.GraphDescription.CreateGraph(
    material_or_name,
    nodeSpaceId=maxon.Id(RS_NODE_SPACE_ID),
    createEmpty=False,
)
if graph is None:
    raise RuntimeError("failed to create or obtain Redshift material graph")
```

For a new material, locate the created material by exact name after the call and fail if it is not unique. Add the new material to the undo stack when Cinema 4D exposes an undo type for it; otherwise return `undo_supported:false`. Never call graph clear/delete commands.

- [ ] Implement and register `src/tools/rs-create-material.ts`. Use `z.string().trim().min(1)` for names. Extend the TS test to assert registration and the exact request payload without asserting the intermediate registry length.

- [ ] Run focused GREEN plus the Task 1 regression:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_*.py" -v
npx vitest run tests/unit/redshift-tools.test.ts tests/unit/get-capabilities.test.ts
npm run build
```

- [ ] Commit Task 2 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/materials.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_materials.py src/tools/rs-create-material.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: create Redshift node materials"
```

---

## Task 3: Set the first PBR material channels and textures

**Files:**

- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/materials.py`
- Modify: `tests/python/test_redshift_materials.py`
- Create: `src/tools/rs-set-material-pbr.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interface produced:**

```ts
type TextureInput = { path: string; color_space?: string };

rs_set_material_pbr({
  document_name?: string;
  material: { kind: "material"; name: string };
  base_color?: [number, number, number] | TextureInput;
  metalness?: number | TextureInput;
  roughness?: number | TextureInput;
  normal?: { texture: TextureInput; strength?: number };
  displacement?: { texture: TextureInput; scale?: number };
  replace_graph?: boolean;
}): Promise<{
  document_name: string;
  material: { kind: "material"; name: string };
  updated_channels: string[];
  created_nodes: Array<{ id: string; asset_id: string }>;
  color_spaces: Record<string, string>;
  replaced_graph: boolean;
  undo_supported: boolean;
  rollback: "not_needed" | "succeeded" | "partial" | "unavailable";
}>;
```

**Interfaces consumed:** existing material handle schema, `require_texture_path`, Redshift node-space graph, `GraphDescription.ApplyDescription`, and existing low-level graph helpers in `node_materials.py`. Existing `apply_graph_description`, `set_graph_port`, and `remove_graph_node` remain public for arbitrary low-level work.

- [ ] Extend Python tests to cover scalar/color values, all five texture routes, default/override color spaces, supplied-channel-only updates, absent material, invalid path zero-write, missing node asset zero-write, transaction exception, and the destructive guard. Required assertions:

```python
with self.assertRaisesRegex(ValueError, "replace_graph.*document_name"):
    handle_rs_set_material_pbr({
        "material": {"kind": "material", "name": "RS_Mat"},
        "replace_graph": True,
        "roughness": 0.35,
    })
self.assertEqual(self.graph_mutation_calls, [])

with self.assertRaisesRegex(ValueError, "file not found"):
    handle_rs_set_material_pbr({
        "material": {"kind": "material", "name": "RS_Mat"},
        "normal": {"texture": {"path": "C:/missing/normal.png"}},
    })
self.assertEqual(self.graph_mutation_calls, [])

self.assertEqual(result["color_spaces"]["base_color"], "color")
self.assertEqual(result["color_spaces"]["roughness"], "raw")
```

- [ ] Add the TS tool and schema tests. Constrain RGB components to `0..1`, metalness/roughness/normal strength to `0..1`, and require `displacement.scale` to be finite. Add a cross-field `.superRefine` requiring `document_name` when `replace_graph === true`. Confirm RED:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_materials.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
```

- [ ] Implement a two-phase PBR writer. Phase 1 resolves the unique material, validates every supplied texture, verifies the Standard Material/Texture Sampler/Bump Map/Displacement assets, and builds an immutable operation list. Phase 2 opens one graph transaction and applies only that list. Use exact Redshift asset IDs:

```python
NODE_ASSETS = {
    "output": "com.redshift3d.redshift4c4d.node.output",
    "standard": "com.redshift3d.redshift4c4d.nodes.core.standardmaterial",
    "texture": "com.redshift3d.redshift4c4d.nodes.core.texturesampler",
    "bump": "com.redshift3d.redshift4c4d.nodes.core.bumpmap",
    "displacement": "com.redshift3d.redshift4c4d.nodes.core.displacement",
}
```

Use ID-based or lazy-ID GraphDescription references, never English labels. The required Standard Material ports are `#~.base_color`, `#~.metalness`, and `#~.refl_roughness`; texture paths use `#~.tex0/path`. Resolve Normal and Displacement input/output ports from the runtime graph and fail before mutation if the exact port cannot be found.

- [ ] Implement texture color handling as a logical policy, then map to the running node's exact color-space port. With no override, Base Color returns normalized policy `color` and lets the active OCIO configuration perform normal color-data handling; Metalness, Roughness, Normal, and Displacement set the texture node to its raw/data mode and return `raw`. A caller-provided `color_space` is applied exactly and echoed; an unknown value fails instead of substituting another space.

- [ ] For `replace_graph:false`, query the existing Standard Material/output nodes and update only supplied channels, creating only the texture/helper nodes required for those channels. For `replace_graph:true`, validate everything first, snapshot the graph when the API exposes a clone/serialization route, clear and rebuild one Output -> Standard graph, and report rollback accurately. If the runtime cannot snapshot/recover graph state, reject replacement with a specific unsupported error instead of making an unprotected destructive edit.

- [ ] Register `rs_set_material_pbr`, extend the TS test to verify registration and forwarding behavior, and run GREEN:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_materials.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

- [ ] Commit Task 3 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/materials.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_materials.py src/tools/rs-set-material-pbr.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: wire Redshift PBR materials"
```

---

## Task 4: Create Redshift lights and camera

**Files:**

- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/lights.py`
- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/camera.py`
- Create: `tests/python/test_redshift_lights_camera.py`
- Create: `src/tools/rs-create-light.ts`
- Create: `src/tools/rs-set-camera.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interfaces produced:**

```ts
rs_create_light({
  document_name?: string;
  name: string;
  type: "area" | "dome" | "sun" | "point" | "spot";
  update_if_exists?: boolean;
  position?: [number, number, number];
  rotation?: [number, number, number];
  color?: [number, number, number];
  intensity?: number;
  exposure?: number;
  dome_texture?: string;
}): Promise<{
  document_name: string;
  handle: { kind: "object"; path: string; name: string };
  type: "area" | "dome" | "sun" | "point" | "spot";
  created: boolean;
  applied: string[];
  undo_supported: boolean;
}>;

rs_set_camera({
  document_name?: string;
  name: string;
  update_if_exists?: boolean;
  position?: [number, number, number];
  rotation?: [number, number, number];
  exposure?: number;
  shutter_time?: number;
  shutter_angle?: number;
  focus_distance?: number;
  f_stop?: number;
  depth_of_field?: boolean;
}): Promise<{
  document_name: string;
  handle: { kind: "object"; path: string; name: string };
  created: boolean;
  applied: string[];
  unavailable: Array<{ setting: string; reason: string }>;
  undo_supported: boolean;
}>;
```

**Interfaces consumed:** `c4d.BaseObject(c4d.Orslight)`, `c4d.BaseObject(c4d.Orscamera)`, Redshift resource constants, document object iteration, and shared document/capability/path helpers.

- [ ] Write Python tests for each light enum, per-type unavailable symbols, exact type preservation during update, Dome texture path validation, duplicate names, camera creation/update, partial camera parameter availability, transform writes, and restoration after error. A representative unsupported test:

```python
delattr(self.c4d, "REDSHIFT_LIGHT_TYPE_SUN")
with self.assertRaisesRegex(RuntimeError, "sun.*unsupported"):
    handle_rs_create_light({"name": "RS_Sun", "type": "sun"})
self.assertEqual(self.document.inserted_objects, [])
```

- [ ] Add both TS tools and schema tests, then confirm RED. Numeric values must be finite; RGB stays in `0..1`; intensity, shutter time, focus distance, and f-stop must be positive; transforms are fixed 3-tuples.

```powershell
python -m unittest discover -s tests/python -p "test_redshift_lights_camera.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
```

- [ ] Implement light type mapping only from runtime symbols:

```python
LIGHT_TYPE_SYMBOLS = {
    "area": "REDSHIFT_LIGHT_TYPE_AREA",
    "dome": "REDSHIFT_LIGHT_TYPE_DOME",
    "sun": "REDSHIFT_LIGHT_TYPE_SUN",
    "point": "REDSHIFT_LIGHT_TYPE_POINT",
    "spot": "REDSHIFT_LIGHT_TYPE_SPOT",
}
```

Create `c4d.Orslight`, set `REDSHIFT_LIGHT_TYPE`, and apply only requested properties. Resolve color/intensity/exposure constants with `getattr`; a missing requested property is an error before insertion. For Dome texture use a nested `DescID` with `REDSHIFT_LIGHT_DOME_TEX0`, the runtime datatype ID, `Orslight`, and `REDSHIFT_FILE_PATH`; validate the file first. Never convert a Standard light or substitute a different Redshift type.

- [ ] Implement camera creation/update using `c4d.Orscamera`. Map requested settings exactly:

```python
CAMERA_PARAMETER_SYMBOLS = {
    "exposure": "RSCAMERAOBJECT_EXPOSURE",
    "shutter_time": "RSCAMERAOBJECT_SHUTTER_TIME_RATIO",
    "shutter_angle": "RSCAMERAOBJECT_SHUTTER_ANGLE",
    "focus_distance": "RSCAMERAOBJECT_FOCUS_DISTANCE",
    "f_stop": "RSCAMERAOBJECT_FNUMBER_VALUE",
    "depth_of_field": "RSCAMERAOBJECT_BOKEH_ENABLED",
}
```

Unlike lights, the camera result has `applied` and `unavailable` arrays: apply every available requested parameter, list unavailable exact names with reasons, and never substitute. Duplicate semantics match the design: absent name creates; unique existing requires `update_if_exists:true`; duplicates fail.

- [ ] Register both tools, extend the TS test to verify registration and forwarding behavior, and run GREEN:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_lights_camera.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

- [ ] Commit Task 4 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/lights.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/camera.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_lights_camera.py src/tools/rs-create-light.ts src/tools/rs-set-camera.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: control Redshift lights and camera"
```

---

## Task 5: List and upsert Redshift AOVs

**Files:**

- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/aovs.py`
- Create: `tests/python/test_redshift_aovs.py`
- Create: `src/tools/rs-list-aovs.ts`
- Create: `src/tools/rs-upsert-aov.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/capabilities.py`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interfaces produced:**

```ts
type RsAovRecord = {
  index: number;
  type: number;
  type_alias?: string;
  name: string;
  enabled: boolean;
  multipass_enabled: boolean;
  direct_file_enabled: boolean;
  direct_file_path: string;
  params: Record<string, boolean | number | string>;
};

rs_list_aovs({ document_name?: string; render_data_name?: string }): Promise<{
  render_data: { kind: "render_data"; name: string };
  aovs: RsAovRecord[];
  count: number;
}>;

rs_upsert_aov({
  document_name?: string;
  render_data_name?: string;
  type: string | number;
  name: string;
  enabled?: boolean;
  multipass_enabled?: boolean;
  direct_file_enabled?: boolean;
  direct_file_path?: string;
  params?: Record<string, boolean | number | string>;
}): Promise<{
  render_data: { kind: "render_data"; name: string };
  aov: RsAovRecord;
  created: boolean;
  rollback: "not_needed" | "succeeded" | "partial" | "unavailable";
}>;
```

**Interfaces consumed:** `redshift.FindAddVideoPost`, `RendererGetAOVs`, `RendererSetAOVs`, `RSAOV`, `VPrsrenderer`, Redshift AOV constants, and RenderData lookup.

- [ ] Write Python tests for empty/list serialization, active or named RenderData, alias/raw-type normalization, create/update, duplicate name/type ambiguity, output path validation, arbitrary raw parameter validation, missing AOV API, and `RendererSetAOVs` exception rollback. Assert the list snapshot includes index, type, name, enabled, multipass, direct-file state, path, and additional safe parameters.

- [ ] Add TS schemas. `type` accepts `z.string().trim().min(1)` or an integer. If `direct_file_enabled:true`, require `direct_file_path`; the path is still validated authoritatively in Python. Confirm RED:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_aovs.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
```

- [ ] Implement AOV alias discovery from optional `c4d.REDSHIFT_AOV_TYPE_*` constants. Include these public aliases when the exact symbol exists: `beauty`, `diffuse_lighting`, `reflection`, `refraction`, `depth`, `normal`, `cryptomatte`, and `object_id`. Return the supported alias map in `rs_get_capabilities`; accept a raw integer for an installed type not in the map.

- [ ] Implement AOV records and one mutation boundary:

```python
def _aov_record(aov, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "type": int(aov.GetParameter(c4d.REDSHIFT_AOV_TYPE)),
        "name": str(aov.GetParameter(c4d.REDSHIFT_AOV_NAME) or ""),
        "enabled": bool(aov.GetParameter(c4d.REDSHIFT_AOV_ENABLED)),
        "multipass_enabled": bool(
            aov.GetParameter(c4d.REDSHIFT_AOV_MULTIPASS_ENABLED)
        ),
        "direct_file_enabled": bool(aov.GetParameter(c4d.REDSHIFT_AOV_FILE_ENABLED)),
        "direct_file_path": str(aov.GetParameter(c4d.REDSHIFT_AOV_FILE_PATH) or ""),
        "params": _safe_aov_params(aov),
    }
```

Take `original = list(RendererGetAOVs(video_post))`, build a separate proposed list, and call `RendererSetAOVs` once. For update, require exactly one existing record matching normalized type and name. On failure, try restoring the original list and report/raise with rollback status.

- [ ] Register both tools, extend the TS test to verify registration and forwarding behavior, and run GREEN:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_aovs.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

- [ ] Commit Task 5 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/aovs.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/capabilities.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_aovs.py src/tools/rs-list-aovs.ts src/tools/rs-upsert-aov.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: list and upsert Redshift AOVs"
```

---

## Task 6: Guarded AOV removal and clear with rollback

**Files:**

- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/aovs.py`
- Modify: `tests/python/test_redshift_aovs.py`
- Create: `src/tools/rs-remove-aov.ts`
- Create: `src/tools/rs-clear-aovs.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interfaces produced:**

```ts
rs_remove_aov({
  document_name?: string;
  render_data_name?: string;
  index: number;
  expected_name: string;
  expected_type: string | number;
}): Promise<{
  render_data: { kind: "render_data"; name: string };
  removed: RsAovRecord;
  remaining_count: number;
  rollback: "not_needed" | "succeeded" | "partial" | "unavailable";
}>;

rs_clear_aovs({
  document_name: string;
  render_data_name?: string;
  force: true;
}): Promise<{
  render_data: { kind: "render_data"; name: string };
  removed: RsAovRecord[];
  remaining_count: 0;
  rollback: "not_needed" | "succeeded" | "partial" | "unavailable";
}>;
```

**Interfaces consumed:** Task 5 AOV snapshot/serialization/setter helpers and shared required document scope.

- [ ] Extend Python tests for stale-index protection, out-of-range index, expected name/type mismatch, successful removal, clear guard, successful clear, recoverable failure, partial clone-less rollback, and active-document restoration. Stale input must produce zero `RendererSetAOVs` calls:

```python
with self.assertRaisesRegex(ValueError, "stale AOV index"):
    handle_rs_remove_aov({
        "index": 0,
        "expected_name": "Old Name",
        "expected_type": "depth",
    })
self.assertEqual(self.redshift.set_aov_calls, [])
```

- [ ] Add TS tools. `rs_clear_aovs.force` must be `z.literal(true)`, not an optional boolean. Confirm RED with Python and TS focused runs.

- [ ] Implement remove by reading one fresh snapshot, validating both expected name and normalized type against the indexed record, removing from a proposed list, and calling `RendererSetAOVs` once. Return the exact removed pre-mutation record.

- [ ] Implement clear with `document_scope(document_name, required=True)` and force validation before capability probing can create a VideoPost. Clone each `RSAOV` when `GetClone`/`Clone` exists; otherwise serialize all safely writable fields. On exception, restore clones or reconstructed records and set rollback to `succeeded`, `partial`, or `unavailable`. On success return `rollback:"not_needed"`.

- [ ] Register both tools, extend the TS test to verify registration and forwarding behavior, and run GREEN:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_aovs.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

- [ ] Commit Task 6 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/aovs.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_aovs.py src/tools/rs-remove-aov.ts src/tools/rs-clear-aovs.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: remove Redshift AOVs safely"
```

---

## Task 7: Configure a Redshift RenderData without implicit activation

**Files:**

- Create: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/render.py`
- Create: `tests/python/test_redshift_render.py`
- Create: `src/tools/rs-configure-render.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interface produced:**

```ts
rs_configure_render({
  document_name?: string;
  name: string;
  update_if_exists?: boolean;
  make_active?: boolean;
  width?: number;
  height?: number;
  frame?: number;
  output_format?: "png" | "jpg" | "tif" | "exr";
  beauty_path?: string;
  multipass_path?: string;
  redshift_params?: Record<string, boolean | number | string>;
}): Promise<{
  document_name: string;
  handle: { kind: "render_data"; name: string };
  created: boolean;
  active: boolean;
  renderer_id: 1036219;
  video_post_id: 1036219;
  rollback: string;
}>;
```

**Interfaces consumed:** existing RenderData traversal/summary helpers, `c4d.documents.RenderData`, `redshift.FindAddVideoPost`, path validators, and Task 5 AOV VideoPost lookup behavior.

- [ ] Write Python tests for create/update, duplicate rejection, renderer forced to `1036219`, VideoPost creation, resolution/frame/format/path writes, raw Redshift params, `make_active:false` preservation, `make_active:true`, invalid path zero-write, missing VideoPost API, and rollback after a late write error.

- [ ] Add TS schema and forwarding tests. Width/height are positive integers, frame is an integer, names are non-empty, and path strings are non-empty. Confirm RED.

- [ ] Implement complete validation into a proposed settings record before creating/updating RenderData. Snapshot an existing RenderData with `GetClone` where available. Apply only after validation:

```python
rd[c4d.RDATA_RENDERENGINE] = RS_RENDERER_ID
rd[c4d.RDATA_XRES] = float(width)
rd[c4d.RDATA_YRES] = float(height)
rd[c4d.RDATA_FRAMESEQUENCE] = FRAME_SEQUENCE_ALIASES["current"]
rd[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(frame, doc.GetFps())
rd[c4d.RDATA_FRAMETO] = c4d.BaseTime(frame, doc.GetFps())
video_post = redshift.FindAddVideoPost(rd, redshift.VPrsrenderer)
```

Map formats exactly to Cinema 4D filter constants and the matching RenderData fields. Validate Beauty/multipass parents as writable without creating files. Apply `redshift_params` only to the Redshift VideoPost, after converting string keys to integer IDs. Do not call `SetActiveRenderData` unless `make_active:true`.

- [ ] On an error after a new RenderData was inserted, remove it. On an error updating an existing RenderData, copy the cloned data/VideoPost state back when supported and report the rollback outcome in the raised error. Never change the document's active RenderData as an error-recovery shortcut.

- [ ] Register the tool, extend the TS test to verify registration and forwarding behavior, and run GREEN:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_render.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

- [ ] Commit Task 7 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/render.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_render.py src/tools/rs-configure-render.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: configure Redshift render data"
```

---

## Task 8: Guarded synchronous Redshift render and output manifest

**Files:**

- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/render.py`
- Modify: `tests/python/test_redshift_render.py`
- Create: `src/tools/rs-render.ts`
- Modify: `plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py`
- Modify: `src/tools/index.ts`
- Modify: `tests/unit/redshift-tools.test.ts`

**Interface produced:**

```ts
rs_render({
  document_name: string;
  render_data_name: string;
  output_path: string;
  force: true;
  overwrite?: boolean;
}): Promise<{
  document_name: string;
  render_data: { kind: "render_data"; name: string };
  renderer: { id: 1036219; name: string };
  width: number;
  height: number;
  beauty: { path: string; size: number };
  aovs: Array<{ index: number; name: string; type: number; path: string; size: number }>;
  expected_missing: Array<{ name: string; path: string; reason: string }>;
  duration_ms: number;
  warnings: string[];
}>;
```

**Interfaces consumed:** Task 7 RenderData lookup/configuration, Task 5 AOV records, `c4d.documents.RenderDocument`, `c4d.bitmaps.MultipassBitmap`, and shared required-document/output validation.

- [ ] Extend Python tests for every guard: missing `document_name`, `force` not exactly true, relative output, missing/unwritable parent, existing output without overwrite, unknown/duplicate RenderData, non-Redshift renderer, missing Redshift VideoPost, failed bitmap allocation, non-OK render result, save failure, AOV manifest collection, missing expected AOV, and active-document restoration after render failure. Every validation failure must assert `RenderDocument` was never called and no file was created.

- [ ] Add TS schema tests requiring non-empty document/RenderData names, `force:z.literal(true)`, and an output path. Set the client request timeout to `1_800_000` milliseconds and document that timeout does not cancel Cinema 4D. Confirm RED.

- [ ] Implement preflight in this exact order: resolve unique document; resolve unique RenderData; validate output/overwrite; require renderer ID `1036219`; locate the `1036219` Redshift VideoPost; read AOV snapshot and expected output paths; allocate the bitmap. Only then call `RenderDocument`.

- [ ] Clone RenderData for the render call, set only the clone's Beauty path, and keep the source RenderData unchanged. Use external full-fidelity flags supported by the runtime. Reject any render-result code other than `RENDERRESULT_OK`; do not retry with another renderer. Save Beauty with the configured filter, then `os.stat` every output path. Missing AOV files are records in `expected_missing`, not fabricated successes.

- [ ] Measure duration with `time.perf_counter()`. Return renderer ID/name, Beauty and AOV paths/sizes, warnings, and missing expected outputs. If the request eventually returns after an MCP-side timeout, preserve the actual render result; never emit “cancelled”.

- [ ] Register the tool, extend the TS test to verify registration and forwarding behavior, and run GREEN. The final catalog count remains a generated-document acceptance check in Task 9, not a unit-test change detector:

```powershell
python -m unittest discover -s tests/python -p "test_redshift_render.py" -v
npx vitest run tests/unit/redshift-tools.test.ts
npm run build
```

- [ ] Commit Task 8 files only:

```powershell
git add plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/render.py plugin/cinema4d_mcp_bridge/bridge/handlers/redshift/__init__.py tests/python/test_redshift_render.py src/tools/rs-render.ts src/tools/index.ts tests/unit/redshift-tools.test.ts
git commit -m "feat: render Redshift outputs safely"
```

---

## Task 9: Strict Cinema 4D 2025.3.2 Redshift proof, docs, install, and release gates

**Files:**

- Create: `tests/e2e/redshift-2025.test.ts`
- Create: `tests/unit/redshift-live-policy.test.ts`
- Modify: `tests/e2e/harness.ts`
- Modify: `tests/unit/foundation-cleanup.test.ts`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `docs/CODEX_SETUP.md`
- Modify: `docs/COMPATIBILITY.md`
- Regenerate: `docs/TOOLS.md`

**Interfaces produced:**

```ts
export function requireRedshiftCapabilities(capabilities: unknown): asserts capabilities is {
  renderer: { supported: true; id: 1036219 };
  module: { supported: true };
  node_space: { supported: true; id: string; node_template_count: number };
  aov_api: { supported: true; aliases: Record<string, number> };
  materials: { supported: true };
  lights: { types: Record<string, { supported: boolean }> };
  camera: { supported: true };
  render: { supported: true };
};
```

**Interfaces consumed:** all eleven `rs_*` tools, existing strict foundation policy, `closeDocumentIfPresent`, document-scoped `batch`, `assign_material`, and local temporary-file APIs.

- [ ] Add `tests/unit/redshift-live-policy.test.ts` before changing the harness. It must reject wrong renderer ID, absent module, wrong node-space ID, zero node-template count, missing AOV setter, unavailable Area/Dome light, unavailable camera/render, and accept only the complete expected snapshot. Run it and confirm RED because `requireRedshiftCapabilities` is missing.

- [ ] Implement `requireRedshiftCapabilities` in the harness without weakening `requireLiveBridge`. The strict Redshift test must first call `requireLiveBridge(probe, baseCapabilities, {tokenRequired:true, execPython:false})`, then the Redshift policy. Token authentication is mandatory for this gate even if the ordinary foundation gate can mirror an unauthenticated environment.

- [ ] Add `tests/e2e/redshift-2025.test.ts`. Use `randomUUID()` for the disposable document name and `mkdtempSync` for outputs. Embed one valid 1x1 PNG byte fixture and write it into the temporary directory. Before mutation, snapshot `list_documents` and require exactly one active document. Set `creationAttempted = true` before calling `new_document({name, make_active:false})`, matching the proven idempotent cleanup pattern.

- [ ] Implement the strict live scene in this order:

```ts
await c.call("new_document", { name: documentName, make_active: false });

await c.call("batch", {
  document_name: documentName,
  undo_group: false,
  stop_on_error: true,
  ops: [
    { op: "create_entity", args: { kind: "object", type_id: "sphere", name: sphereName } },
    { op: "create_entity", args: { kind: "object", type_id: "plane", name: floorName } },
  ],
});

await c.call("rs_create_material", { document_name: documentName, name: materialName });
await c.call("rs_set_material_pbr", {
  document_name: documentName,
  material: { kind: "material", name: materialName },
  base_color: { path: texturePath },
  metalness: 0.15,
  roughness: 0.35,
});
```

Then create one Area and one Dome light, create a camera, assign the material through a document-scoped batch, choose at least one supported common AOV from capability aliases, upsert it with a direct path, configure `64x64` Redshift RenderData, and call `rs_render` with `force:true` and `overwrite:false`.

- [ ] Prove zero-write validation in the live scene. Snapshot `list_graph_nodes` for the material, call `rs_set_material_pbr` with a missing absolute texture path, require an MCP error, then compare graph snapshots exactly. Also assert the active user document did not change after the rejected call.

- [ ] Assert the render manifest: renderer ID is `1036219`; Beauty path matches; Beauty size is greater than zero; at least one AOV entry exists and each reported file is non-empty; `expected_missing` is empty; width/height are `64`; duration is non-negative. Assert source RenderData remains named correctly and no fallback renderer appears.

- [ ] Make cleanup unconditional and idempotent. In both the test-local `finally` and `afterAll`, call `closeDocumentIfPresent` only when creation was attempted. Remove the temporary directory after closing the document. After successful close, require `list_documents` to equal the original snapshot including exact active focus. Extend `tests/unit/foundation-cleanup.test.ts` only if a new cleanup helper is introduced.

- [ ] Add the strict command:

```json
"test:live:redshift:2025": "node --input-type=module -e \"import { spawnSync } from 'node:child_process'; const result = spawnSync(process.execPath, ['node_modules/vitest/vitest.mjs', 'run', 'tests/e2e/redshift-2025.test.ts'], { stdio: 'inherit', env: { ...process.env, C4D_MCP_REQUIRE_LIVE: '1' } }); process.exit(result.status ?? 1)\""
```

Run the policy and cleanup unit tests first:

```powershell
npx vitest run tests/unit/redshift-live-policy.test.ts tests/unit/foundation-cleanup.test.ts
```

- [ ] Regenerate and inspect tool docs:

```powershell
npm run docs:tools
rg -n "76 tools across 17 groups|rs_get_capabilities|rs_create_material|rs_render" docs/TOOLS.md
```

Expected: one generated Redshift section, all eleven tools, `76 tools across 17 groups`.

- [ ] Update documentation only with verified boundaries. README changes its catalog count from `65/16` to `76/17`, gets one complete natural-language example sequence, and warns about `replace_graph`, clear-all AOV, formal render, synchronous timeouts, and exact-document targeting. `docs/CODEX_SETUP.md` gets the strict command and manual restart/install sequence. `docs/COMPATIBILITY.md` lists each Redshift operation as “offline-tested” until the strict live command passes; only after a non-skipped pass may those exact rows become “Redshift live-verified”, with date/runtime/security/renderer evidence.

- [ ] Run every offline gate with bridge-dependent suites forced to an unreachable port:

```powershell
python -m unittest discover -s tests/python -p "test_*.py" -v
$env:C4D_MCP_PORT = "65534"
npm test
Remove-Item Env:C4D_MCP_PORT
npm run check
npm run build
npm audit --audit-level=high
```

Expected: all Python tests pass; all non-live Vitest tests pass; bridge suites visibly skip rather than connect; check/build exit `0`; audit reports zero high-or-greater vulnerabilities.

- [ ] Run the installer dry-run against the known Cinema 4D 2025 preference and inspect source/destination/backup lines. This command must not write:

```powershell
npm run install:c4d -- --dry-run --preference "C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B"
```

- [ ] Apply the install only after the dry-run points to `cinema4d_mcp_bridge`, then verify the installer created a timestamped backup of the previous destination:

```powershell
npm run install:c4d -- --install --preference "C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B"
```

Tell the user to restart Cinema 4D manually. Do not close or restart it from the implementation session.

- [ ] After the user confirms Cinema 4D restarted, run both non-skippable live gates with the existing authenticated environment:

```powershell
npm run test:live:2025
npm run test:live:redshift:2025
```

Expected: foundation has one passing test and zero skips; Redshift has one passing test and zero skips; exact C4D 2025.3.2, bridge 0.4.0, loopback, token required, `exec_python:false`, Redshift renderer/module/node-space/AOV API all pass.

- [ ] After both strict gates pass, update `docs/COMPATIBILITY.md` with the exact command date, raw/display version, bridge version, security snapshot, Redshift renderer/node-space/AOV evidence, Beauty/AOV file sizes, and cleanup/focus assertion. Run `npm run check` again. If either strict gate fails or skips, keep the rows “offline-tested” and record the blocker without promoting compatibility.

- [ ] Verify every tracked installed plugin source file matches the repository copy by relative path and SHA-256. Ignore generated `__pycache__` files, but fail on a missing or mismatched tracked source. Re-run both live gates if any mismatch required another install/restart.

```powershell
$sourceRoot = (Resolve-Path "plugin\cinema4d_mcp_bridge").Path
$installedRoot = "C:\Users\Yihong\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_789E552B\plugins\cinema4d_mcp_bridge"
$relativeFiles = git ls-files "plugin/cinema4d_mcp_bridge/*" | ForEach-Object { $_.Substring("plugin/cinema4d_mcp_bridge/".Length) }
$mismatches = foreach ($relative in $relativeFiles) {
  $sourceFile = Join-Path $sourceRoot $relative
  $installedFile = Join-Path $installedRoot $relative
  if (-not (Test-Path -LiteralPath $installedFile -PathType Leaf)) {
    "missing: $relative"
    continue
  }
  $sourceHash = (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash
  $installedHash = (Get-FileHash -LiteralPath $installedFile -Algorithm SHA256).Hash
  if ($sourceHash -ne $installedHash) { "mismatch: $relative" }
}
if ($mismatches) { $mismatches; throw "installed plugin hash verification failed" }
"installed plugin hashes match: $($relativeFiles.Count)/$($relativeFiles.Count)"
```

- [ ] Perform final scope review:

```powershell
$unfinishedMarkers = @("TO" + "DO", "TB" + "D", "<place" + "holder>")
Get-ChildItem plugin/cinema4d_mcp_bridge/bridge/handlers/redshift,src/tools,tests/python,tests/e2e,README.md,docs -Recurse -File | Select-String -Pattern $unfinishedMarkers
git diff --check
git status --short
```

Expected: no unfinished markers, no whitespace errors, and no uncommitted Redshift files. Unrelated user-owned files may still appear; do not modify, stage, stash, or discard them. A literally clean whole worktree is a user-owned follow-up prerequisite when unrelated changes exist, not permission to alter those files.

- [ ] Commit the live harness and documentation, staging only Task 9 files:

```powershell
git add tests/e2e/redshift-2025.test.ts tests/unit/redshift-live-policy.test.ts tests/e2e/harness.ts tests/unit/foundation-cleanup.test.ts package.json README.md docs/CODEX_SETUP.md docs/COMPATIBILITY.md docs/TOOLS.md
git commit -m "test: verify Redshift production path"
```

- [ ] Report the exact commands, exit codes, pass/skip counts, installed preference path, backup path, hash result, renderer ID, C4D/bridge/security snapshot, Beauty/AOV output sizes, cleanup result, and the preserved unrelated dirty files. Do not claim broader Redshift control than the strict test exercised.

---

## Final specification audit

- [ ] Compare the implementation tool-for-tool with the approved list and confirm exactly eleven public additions: `rs_get_capabilities`, `rs_create_material`, `rs_set_material_pbr`, `rs_create_light`, `rs_set_camera`, `rs_list_aovs`, `rs_upsert_aov`, `rs_remove_aov`, `rs_clear_aovs`, `rs_configure_render`, and `rs_render`.
- [ ] Confirm destructive guards are cross-layer enforced: Zod rejects them at MCP input and Python rejects direct bridge calls before mutation.
- [ ] Confirm every mutator calls the shared capability probe, document focus is restored on success/error, and no handler imports `redshift` eagerly.
- [ ] Confirm unsupported features expose a reason, raw low-level node/parameter tools remain available, and no native C++ layer was added without a proven Python gap.
- [ ] Confirm the strict live suite created only one uniquely named disposable document, rendered 64x64 Beauty+AOV outputs, proved one invalid zero-write request, closed the document, deleted temporary files, and restored the exact original document list/focus.
- [ ] Confirm documentation distinguishes catalog presence, offline-tested behavior, Redshift live-verified behavior, unsupported first-milestone boundaries, and future roadmap work.
