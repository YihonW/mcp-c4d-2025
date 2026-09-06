# Compatibility and verification status

This fork targets Cinema 4D 2025.3.2. A target is not a support claim: foundation compatibility is promoted only by a successful, non-skipped `npm run test:live:2025` run, and Redshift compatibility requires the separate strict `npm run test:live:redshift:2025` gate against the exact runtime named below.

## Current status

| Runtime            | Status                                                   | Evidence boundary                                                                                  |
| ------------------ | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Cinema 4D 2025.3.2 | **Foundation live-verified on Windows x64 (2026-09-05)** | Strict suite: one passing foundation test, zero skips, exit `0`; exact boundary is listed below.   |
| Cinema 4D 2024.x   | **Inherited / unverified**                               | No strict live suite is defined for this release.                                                  |
| Cinema 4D 2026.x   | **Inherited / unverified in this fork**                  | Upstream observations may exist, but they are not current live evidence for this fork or for 2025. |
| Other releases     | **Unsupported / unverified**                             | No compatibility evidence is recorded.                                                             |

Only the exact foundation behaviors below are claimed as live-verified. The 11 Redshift tools are offline-tested but have not yet passed the strict live gate against the installed candidate. No complete tool group and no blanket claim for all 76 tools is implied.

## Evidence labels

- **Inherited / unverified:** implementation or documentation carried from the existing `mcp-cinema4d` codebase, or a tool not exercised by the strict foundation suite. Presence in [TOOLS.md](./TOOLS.md) only means the tool is registered in source.
- **Foundation live-verified:** the exact behavior was exercised by `npm run test:live:2025`, the command exited `0`, the bridge and security snapshot matched the recorded runtime below, and the foundation test had no skip.
- **Redshift read-only verified:** authenticated capability discovery succeeded on the recorded runtime. This does not verify scene mutation or rendering.
- **Redshift offline-tested:** TypeScript schemas and registration plus Python bridge behavior pass fake-runtime regression tests, build, lint, and formatting gates. No real Cinema 4D or Redshift compatibility claim is made until the strict Redshift live gate passes without skips.
- **Unsupported / unverified:** no accepted live evidence exists. This label does not predict whether a tool happens to work.

## Foundation verification boundary

The strict suite currently covers one end-to-end path:

| Area                           | Tools/behavior exercised                                                       | Status                   |
| ------------------------------ | ------------------------------------------------------------------------------ | ------------------------ |
| Connection                     | `ping` through the Codex-style STDIO server and TCP bridge                     | Foundation live-verified |
| Runtime and security discovery | `get_capabilities`; exact runtime, platform, bridge, and security gates        | Foundation live-verified |
| Isolated document              | `new_document` with a unique name and `make_active: false`                     | Foundation live-verified |
| Create, edit, read             | `batch`, `create_entity`, `sample_transform`, `set_transform`                  | Foundation live-verified |
| Undo                           | `undo`, followed by a transform read that must match the pre-edit value        | Foundation live-verified |
| Preview                        | `preview_render` to a 64×64 PNG in a temporary directory                       | Foundation live-verified |
| Save-copy and state            | `get_document_state`, `save_document` with `copy: true`, then state comparison | Foundation live-verified |
| Cleanup                        | Close the uniquely named temporary document and remove temporary files         | Foundation live-verified |

Recorded run: Windows x64, Cinema 4D raw version `2025302` (2025.3.2), Node.js 24.18.0, bridge 0.4.0, loopback transport, token authentication disabled, and `exec_python` disabled. `npm run test:live:2025` exited `0` with one passing foundation test and zero skipped tests on 2026-08-08.

Latest recorded run: the installed source from `a59a10a` passed the same strict suite on 2026-09-05 at 20:42 Beijing time, with **token authentication enabled**, `exec_python` disabled, and the same exact C4D/bridge versions. One test passed, zero skipped, exit `0`. A preceding attempt was rejected before document insertion because the active document was blank. After switching focus to the other already-open, non-blank document, the successful run preserved both original documents and cleaned its single temporary document. See the [integration record](./reports/2026-09-05-redshift-integration.md).

Even after this suite passes, the claim is limited to the exact Cinema 4D build, operating system, bridge version, security posture, and foundation path tested. It does **not** promote all 76 tools or any complete tool group.

## Redshift verification boundary

The following tools are implemented and offline-tested. Only capability discovery has passed a real read-only check; the complete Redshift production path has not passed its strict live gate:

| Area                 | Tools                                                             | Status                      |
| -------------------- | ----------------------------------------------------------------- | --------------------------- |
| Capability discovery | `rs_get_capabilities`                                             | Redshift read-only verified |
| Materials            | `rs_create_material`, `rs_set_material_pbr`                       | Redshift offline-tested     |
| Lights and camera    | `rs_create_light`, `rs_set_camera`                                | Redshift offline-tested     |
| AOVs                 | `rs_list_aovs`, `rs_upsert_aov`, `rs_remove_aov`, `rs_clear_aovs` | Redshift offline-tested     |
| Render setup/output  | `rs_configure_render`, `rs_render`                                | Redshift offline-tested     |

`npm run test:live:redshift:2025` is defined but has not yet been accepted as live evidence. The release candidate must be installed through the reviewed installer, Cinema 4D must be restarted manually with saved user work, token authentication must be enabled, and the command must finish with no skip before these rows can be promoted.

On 2026-09-05, the first candidate's read-only checks found an unresolved asset-type declaration and missing light symbols before creating any test document. Those fixes were installed and, after a manual restart, authenticated capability discovery succeeded: 929 node templates, all five light types, eight AOV aliases, and renderer/module/camera/render support. The strict Redshift suite then failed at `rs_set_material_pbr` with `Standard Material node not found in Redshift graph`, before rendering; its temporary document was cleaned. The SDK returns an `(asset ID, version)` pair, which the code incorrectly converted as a whole to a string. Source now extracts the ID for graph listing, matching, and port lookup, with offline regressions passing; this latest fix still requires reviewed installation and a manual restart before another live test. See the [integration record](./reports/2026-09-05-redshift-integration.md).

Installation update (2026-09-05 20:52 Beijing time): the node-ID fix from `023406e` was installed after confirming Cinema 4D was fully closed. All 70 installed files matched the source by relative path and SHA-256; all 62 files in the previous plugin were preserved and hash-verified in an external backup. Live verification of this latest fix is still pending the user's manual startup.

Retest update (2026-09-05 20:57 Beijing time): the installed `023406e` candidate still failed at standard-material matching, before rendering. A separate, immediately cleaned diagnostic document confirmed that both expected nodes exist, but their asset IDs were still stringified as `(asset-id,)`. Maxon's native pair is indexable without being a Python tuple/list, so the previous type check missed it. The latest source indexes the attribute directly, adds a non-builtin pair regression and an exact node-ID gate before live PBR writes, and passes 96 Python plus 73 TypeScript unit tests. This latest source is not yet installed or live-verified. Both temporary documents used during this retest/diagnostic were closed; no user document was closed or saved.

Installation update (2026-09-06 18:14 Beijing time): the native-pair fix from `9dbc0e6` is now installed, following a reviewed dry-run and confirmation that C4D was fully closed. All 70 installed files match the source, and all 70 previous files were preserved in an external, hash-verified backup. No live test ran during installation; node-ID readback and the strict Redshift production path remain pending manual startup.

## Inherited tool catalog

All tools in [TOOLS.md](./TOOLS.md) outside the foundation boundary and the explicitly offline-tested Redshift boundary—including advanced modeling, mesh, document I/O outside the foundation save-copy path, generic node materials, Xpresso, animation, layers, MoGraph, plugin options, generic render operations, and Python escape hatches—remain inherited/unverified on Cinema 4D 2025.3.2 until a dedicated live test records evidence for them.

`exec_python` is additionally disabled by default and requires `C4D_MCP_ENABLE_EXEC_PYTHON=1` on both the Node and Cinema 4D processes. Creating or editing Python-bearing plugin types requires the independent `C4D_MCP_ENABLE_PYTHON_OPS=1` opt-in on the Cinema 4D side. Enabling either gate changes the security posture and must be recorded with any result.

## Release gate

A release claim requires all of the following evidence from the candidate commit:

1. `npm run build`, `npm test`, and `npm run check` exit `0`.
2. `npm audit --audit-level=high` exits `0`. This gate is satisfied for lockfile commit `d096c18`; rerun it after any dependency or lockfile change.
3. The installer dry-run target is reviewed before an explicit install.
4. `npm run test:live:2025` exits `0` against Cinema 4D 2025.3.2 with no skipped foundation test.
5. `npm run test:live:redshift:2025` exits `0` with token authentication enabled, exact Redshift capabilities, one temporary non-active document, verified Beauty/AOV output, zero-write failure coverage, state restoration, and no skipped test.
6. The recorded evidence names the commit, Node version, Cinema 4D build, bridge version, Redshift capability snapshot, relevant environment gates, command exit codes, and skipped-test count.

Ordinary `npm test` runs unit tests only, never connects to Cinema 4D, and must never be used as the sole live-compatibility signal.
