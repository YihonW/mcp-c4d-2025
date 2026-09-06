# Compatibility and verification status

This fork targets Cinema 4D 2025.3.2. A target is not a support claim: foundation compatibility is promoted only by a successful, non-skipped `npm run test:live:2025` run, and Redshift compatibility requires the separate strict `npm run test:live:redshift:2025` gate against the exact runtime named below.

## Current status

| Runtime            | Status                                                                       | Evidence boundary                                                                                   |
| ------------------ | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Cinema 4D 2025.3.2 | **Foundation and scoped Redshift live-verified on Windows x64 (2026-09-06)** | Both strict suites: one passing test each, zero skips, exit `0`; exact boundaries are listed below. |
| Cinema 4D 2024.x   | **Inherited / unverified**                                                   | No strict live suite is defined for this release.                                                   |
| Cinema 4D 2026.x   | **Inherited / unverified in this fork**                                      | Upstream observations may exist, but they are not current live evidence for this fork or for 2025.  |
| Other releases     | **Unsupported / unverified**                                                 | No compatibility evidence is recorded.                                                              |

Only the exact foundation, Redshift and workflow behaviors below are claimed as live-verified. Installed source `81e319d` passed all three strict suites on 2026-09-06; prior source `4a62967` also passed the two earlier suites. Package 0.4.0 registers 79 tools (78 by default). No complete tool group or blanket support for the full catalog is implied. See the [0.4.0 validation record](./reports/2026-09-06-workflow-validation.md).

## Evidence labels

Version 0.5.0 adds four guarded F-Curve tools (83 registered, 82 by default). Their source and fake-runtime tests are separate from the installed 0.4.0 live evidence above. The 0.5.0 bridge has **not yet been installed or live-verified**; the existing working Cinema 4D session was not restarted. Current strict live suites require the 0.5.0 candidate before any isolated-document tests can run. See [Chinese curve instructions](./WORKFLOW_ZH.md) for supported REAL channels and exclusions, and the [0.5.0 development record](./reports/2026-09-06-fcurve-validation.md) for its separate verification boundary.

- **Inherited / unverified:** implementation or documentation carried from the existing `mcp-cinema4d` codebase, or a tool not exercised by the strict foundation suite. Presence in [TOOLS.md](./TOOLS.md) only means the tool is registered in source.
- **Foundation live-verified:** the exact behavior was exercised by `npm run test:live:2025`, the command exited `0`, the bridge and security snapshot matched the recorded runtime below, and the foundation test had no skip.
- **Redshift read-only verified:** authenticated capability discovery succeeded on the recorded runtime. This does not verify scene mutation or rendering.
- **Redshift live-verified (scoped):** the exact production path below passed the strict Redshift suite with zero skips, verified PNG output, and restored document/render-data state. Unexercised options and failure paths remain offline-tested only.
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

Latest candidate retest: `4a62967` passed on 2026-09-06 at 18:55:34 Beijing time, one test passed, zero skipped, exit `0`, duration 3.93 seconds. Token authentication remained enabled and `exec_python` disabled. Its single temporary document was closed; the original checkpoint and focus were preserved. See the [autonomous validation record](./reports/2026-09-06-autonomous-validation.md).

Even after this suite passes, the claim is limited to the exact Cinema 4D build, operating system, bridge version, security posture, and foundation path tested. It does **not** promote all 76 tools or any complete tool group.

## Redshift verification boundary

The following tools are implemented and offline-tested. The installed candidate also passed the scoped production path listed below; this does not verify every option of each tool:

| Area                   | Tools                                       | Status                          |
| ---------------------- | ------------------------------------------- | ------------------------------- |
| Capability discovery   | `rs_get_capabilities`                       | Redshift read-only verified     |
| Materials              | `rs_create_material`, `rs_set_material_pbr` | Redshift live-verified (scoped) |
| Lights and camera      | `rs_create_light`, `rs_set_camera`          | Redshift live-verified (scoped) |
| AOV list/create/update | `rs_list_aovs`, `rs_upsert_aov`             | Redshift live-verified (scoped) |
| AOV removal/clear      | `rs_remove_aov`, `rs_clear_aovs`            | Redshift offline-tested         |
| Render setup/output    | `rs_configure_render`, `rs_render`          | Redshift live-verified (scoped) |

Accepted run: `npm run test:live:redshift:2025`, installed source `4a62967`, 2026-09-06 at 18:55:09 Beijing time, one test passed, zero skipped, exit `0`, duration 8.04 seconds. Runtime: Windows x64, C4D `2025302` / `2025.3.2`, Python `3.11.4`, Node.js `24.18.0`, bridge `0.4.0`, loopback, token authentication enabled, `exec_python` disabled; Redshift renderer `1036219`, 929 node templates and eight AOV aliases.

Verified scope: one isolated non-active document; exact standard/output node IDs; constant RGB, metalness and roughness plus a base-color texture; Area and textured Dome creation; camera position; sphere material assignment; rejected missing-texture input without graph changes; inactive named 64×64 PNG render settings with explicit sampling parameters; depth AOV creation and existing-AOV update retaining PNG format/depth; Beauty and AOV PNG signatures/IHDR dimensions; no expected missing output; restoration of document state, active RenderData, original documents and focus. Normal/displacement textures, other light types, other AOV types/formats, removal/clear, arbitrary node graphs and all remaining options are **not** promoted by this run.

Installation used the reviewed installer with C4D fully stopped and complete hash-verified external backups. The user authorized autonomous handling, so normal save/quit/start commands were performed by the agent, not forced process termination. A unique temporary Null preserved the original blank checkpoint during tests and was removed afterward. See the [full record](./reports/2026-09-06-autonomous-validation.md); prior unsuccessful attempts are retained below as historical evidence.

On 2026-09-05, the first candidate's read-only checks found an unresolved asset-type declaration and missing light symbols before creating any test document. Those fixes were installed and, after a manual restart, authenticated capability discovery succeeded: 929 node templates, all five light types, eight AOV aliases, and renderer/module/camera/render support. The strict Redshift suite then failed at `rs_set_material_pbr` with `Standard Material node not found in Redshift graph`, before rendering; its temporary document was cleaned. The SDK returns an `(asset ID, version)` pair, which the code incorrectly converted as a whole to a string. Source now extracts the ID for graph listing, matching, and port lookup, with offline regressions passing; this latest fix still requires reviewed installation and a manual restart before another live test. See the [integration record](./reports/2026-09-05-redshift-integration.md).

Installation update (2026-09-05 20:52 Beijing time): the node-ID fix from `023406e` was installed after confirming Cinema 4D was fully closed. All 70 installed files matched the source by relative path and SHA-256; all 62 files in the previous plugin were preserved and hash-verified in an external backup. Live verification of this latest fix is still pending the user's manual startup.

Retest update (2026-09-05 20:57 Beijing time): the installed `023406e` candidate still failed at standard-material matching, before rendering. A separate, immediately cleaned diagnostic document confirmed that both expected nodes exist, but their asset IDs were still stringified as `(asset-id,)`. Maxon's native pair is indexable without being a Python tuple/list, so the previous type check missed it. The latest source indexes the attribute directly, adds a non-builtin pair regression and an exact node-ID gate before live PBR writes, and passes 96 Python plus 73 TypeScript unit tests. This latest source is not yet installed or live-verified. Both temporary documents used during this retest/diagnostic were closed; no user document was closed or saved.

Installation update (2026-09-06 18:14 Beijing time): the native-pair fix from `9dbc0e6` is now installed, following a reviewed dry-run and confirmation that C4D was fully closed. All 70 installed files match the source, and all 70 previous files were preserved in an external, hash-verified backup. No live test ran during installation; node-ID readback and the strict Redshift production path remain pending manual startup.

Retest update (2026-09-06 18:19 Beijing time): the installed `9dbc0e6` candidate passed the exact standard-material and output asset-ID assertions. The single strict Redshift test then failed at `ports.FindChild(maxon.Id(root_id))` with an `InternedId` conversion TypeError, before the PBR graph transaction or any render. One test failed, zero skipped, exit `1`. Its single temporary document and the temporary Null marker used to preserve the original blank document were removed; only the original active document remained, with no objects. No user document was closed or saved, although marker creation/removal may leave undo history. Source now passes string IDs for both root and nested port lookup; the stricter fake reproduces the observed failure, and all 96 Python and 73 TypeScript unit tests pass after the fix. This port-lookup patch is **not installed or live-verified**. Capability discovery remains the only promoted Redshift row; successful node-ID assertions do not promote the whole materials workflow.

## Animation and PNG sequence workflow boundary

`npm run test:live:workflow:2025` passed on 2026-09-06 at 19:37:45 Beijing time against installed source `81e319d`: one test passed, zero skipped, exit 0, total 18.56 seconds. The foundation and scoped Redshift suites were also rerun successfully at 19:39:54 and 19:39:58, respectively.

Newly verified: one isolated document; two Null pivots and two independently converted cube meshes preserving hierarchy; direct rotation keys and interpolated/local/global samples; complete REAL user-data DescID keyframe write/read; user-data object-link write/read and rejected missing link preserving the old value; RS material/light/camera setup; seven 128×128 PNG Beauty frames with distinct SHA-256 hashes; PNG chunk CRC/dimensions/file checks; final status/manifest consistency; save-copy and original document/focus restoration.

This verifies a small **rigid parent-hierarchy animation**, not skeletal skinning, IK/FK or a user-data-driven rig. The new `rs_render_sequence`, `rs_sequence_status` and `rs_sequence_control` tools provide bounded same-session jobs. Cancellation/resume, uncertain-transport handling and explicit-frame failure restoration remain offline-tested; successful sequence execution is the promoted live path. No AOV sequence, long/high-resolution production run, cross-process recovery or simulation-cache guarantee is made. Full details and the earlier corrected angular assertion are in the [workflow validation record](./reports/2026-09-06-workflow-validation.md).

## Inherited tool catalog

All behavior in [TOOLS.md](./TOOLS.md) outside the three explicit verification boundaries remains unverified on Cinema 4D 2025.3.2. This includes untested advanced modeling/mesh operations, other document I/O, generic node materials, Xpresso, other animation options, layers, MoGraph, plugin options, generic render operations and Python escape hatches. Newly added animation-path/reference/sequence failure cases have offline regressions; that is not live compatibility evidence.

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
