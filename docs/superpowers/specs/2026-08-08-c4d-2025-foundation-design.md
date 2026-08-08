# Cinema 4D 2025 MCP Foundation Design

## Goal

Build a safe, typed MCP bridge that Codex can use to inspect and edit a live Cinema 4D 2025.3.2 session. The first milestone proves version compatibility and the complete connection/edit/undo/preview/save-copy path before advanced renderer and native C++ capability packs are added.

## Baseline and reuse

- Start from `kumoproductions/mcp-cinema4d` at commit `1d27d8e3078afe3429e550a66676cf6226b19ba6` under its MIT license.
- Keep the upstream TypeScript MCP server, modular Cinema 4D Python plugin, JSON-Lines TCP bridge, typed entity handles, undo-aware mutations, and E2E harness.
- Preserve upstream copyright and license notices.
- Treat `sdimaging/cinema4d-mcp` and `cuneytozseker/mcp4d` as design references for later capability packs; do not copy code until its license and version-specific behavior are recorded in that pack's plan.

## Supported baseline

- Windows 10/11 x64.
- Cinema 4D 2025.3.2 is the first verified target.
- Cinema 4D's embedded Python 3.11.
- Node.js 24 or newer for the local MCP process.
- Codex connects through local STDIO MCP.
- The bridge binds to `127.0.0.1` by default.

Versions other than Cinema 4D 2025.x remain unverified until they pass the same live test suite. The server must report runtime capabilities instead of assuming every SDK symbol exists.

## Architecture

1. `src/` is a TypeScript MCP facade. It validates tool inputs, converts responses to MCP content, and sends authenticated requests to Cinema 4D.
2. `plugin/cinema4d_mcp_bridge/` is a modular Python plugin loaded by Cinema 4D. A socket thread accepts JSON-Lines requests; all scene access is dispatched onto Cinema 4D's main thread.
3. `scripts/` contains a dry-run-first Windows installer/doctor. It installs the plugin into the current user's Cinema 4D preferences, never into `Program Files`.
4. A future C++ 2025 helper will be a separate optional component for viewport, raycast, and SDK operations that Python cannot perform reliably. It is not part of the foundation milestone.
5. A future `c4dpy` worker will be a separate process for headless batch work. It will never claim to control the active GUI session.

## Runtime contract

The existing request envelope remains:

```json
{ "id": "uuid", "token": "shared-secret", "command": "get_capabilities", "params": {} }
```

The bridge returns either:

```json
{ "id": "uuid", "status": "ok", "result": {} }
```

or:

```json
{ "id": "uuid", "status": "error", "error": "structured human-readable message" }
```

`get_capabilities` must return the numeric and display Cinema 4D version, operating system, Python version, bridge version, security state, supported tool groups, optional SDK features, and detected renderer/plugin identifiers. Unsupported features are reported explicitly and are not registered as successful capabilities.

## Security model

- Loopback-only binding is the default. Remote binding requires explicit opt-in.
- A random shared token is recommended by the installer and compared with constant-time equality.
- Arbitrary Python execution remains disabled unless both MCP process and Cinema 4D plugin opt in.
- The installer defaults to dry-run and requires `--install` before copying files.
- Destructive scene operations must be undo-grouped where Cinema 4D supports undo.
- Save tests write to a temporary path or a caller-specified copy, never overwrite a production scene.
- Future third-party plugin packs use runtime discovery and allowlisted operations; private UI automation stays outside this MCP core.

## Foundation tool scope

The inherited tool surface remains available, but only these groups are release-blocking for the 2025 foundation:

- Health and capabilities: `ping`, `get_capabilities`, plugin listing.
- Document lifecycle: new, inspect, undo, save copy, close temporary document.
- Scene entities: list, create, describe, set parameters and transforms, move, clone, remove.
- Selection, tags, basic materials, cameras, and lights.
- Preview render with bounded output.
- Safe batch execution with structured per-operation results.

Node materials, Scene Nodes, Xpresso, Takes, MoGraph, mesh editing, and modeling commands remain present but are marked capability-dependent until their 2025 live tests pass.

## Compatibility policy

- `2025.x` is `supported` after the live smoke suite passes on the current machine.
- `2024.x` and `2026.x` are `unverified` in this fork until separately tested.
- Older or malformed version values are `unsupported`.
- Version decisions use the numeric result of `c4d.GetC4DVersion()` and do not parse marketing strings.
- Each version-sensitive SDK symbol is accessed through `getattr` or a capability probe before use.

## Testing strategy

1. Unit tests cover TypeScript schemas, version classification, capability formatting, installer path resolution, and security defaults without launching Cinema 4D.
2. Pure Python tests cover compatibility helpers without importing the unavailable `c4d` module.
3. Contract tests ensure every registered MCP tool maps to a bridge command.
4. Live E2E tests use a new temporary document and verify ping, capabilities, cube creation, transform, undo, preview render, and save-copy.
5. Advanced groups remain visibly skipped when capabilities are absent; a skipped live suite is not counted as compatibility proof.

## Foundation acceptance criteria

- `npm run build`, unit tests, Python lint/format checks, and documentation checks exit successfully.
- `get_capabilities` identifies the running application as Cinema 4D 2025.3.2 and reports security state accurately.
- The installer dry-run prints the exact source and destination and performs no write.
- The live smoke suite creates and modifies a temporary cube, undoes the modification, generates a preview, and saves a copy outside production locations.
- `exec_python` is disabled by default and unauthenticated requests are rejected when a token is configured.
- No claim of 2025 compatibility is made until the live smoke suite runs without skips.

## Deferred capability packs

After the foundation is accepted, create separate specifications and plans for:

1. Redshift and node-material workflows.
2. Scene Nodes, Xpresso, Takes, Layers, MoGraph, Fields, and Dynamics.
3. Octane and Insydium/X-Particles adapters based on the plugins installed on the target workstation.
4. A C++ 2025 native helper for viewport capture, raycasting, and fragile modeling operations.
5. A `c4dpy` headless worker for offline conversion, inspection, and rendering.
