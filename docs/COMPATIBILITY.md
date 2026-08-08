# Compatibility and verification status

This fork targets Cinema 4D 2025.3.2. A target is not a support claim: compatibility is promoted only by a successful, non-skipped `npm run test:live:2025` run against the exact runtime named below.

## Current status

| Runtime            | Status                                               | Evidence boundary                                                                                  |
| ------------------ | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Cinema 4D 2025.3.2 | **Target; foundation live verification not yet run** | Build, unit tests, generated docs, and offline checks do not prove the live bridge path.           |
| Cinema 4D 2024.x   | **Inherited / unverified**                           | No strict live suite is defined for this release.                                                  |
| Cinema 4D 2026.x   | **Inherited / unverified in this fork**              | Upstream observations may exist, but they are not current live evidence for this fork or for 2025. |
| Other releases     | **Unsupported / unverified**                         | No compatibility evidence is recorded.                                                             |

At the current status, **no tool group is claimed as live-verified on Cinema 4D 2025.3.2**.

## Evidence labels

- **Inherited / unverified:** implementation or documentation carried from the existing `mcp-cinema4d` codebase, or a tool not exercised by the strict foundation suite. Presence in [TOOLS.md](./TOOLS.md) only means the tool is registered in source.
- **Foundation live-verified:** the exact behavior was exercised by `npm run test:live:2025`, the command exited `0`, the bridge reported a Cinema 4D 2025 runtime, and the foundation test had no skip.
- **Unsupported / unverified:** no accepted live evidence exists. This label does not predict whether a tool happens to work.

## Foundation verification boundary

The strict suite currently covers one end-to-end path:

| Area                           | Tools/behavior exercised                                                       | Status before a successful live run |
| ------------------------------ | ------------------------------------------------------------------------------ | ----------------------------------- |
| Connection                     | `ping` through the Codex-style STDIO server and TCP bridge                     | Pending / unverified                |
| Runtime and security discovery | `get_capabilities`; requires a reported Cinema 4D 2025 release                 | Pending / unverified                |
| Isolated document              | `new_document` with a unique name and `make_active: false`                     | Pending / unverified                |
| Create, edit, read             | `batch`, `create_entity`, `sample_transform`, `set_transform`                  | Pending / unverified                |
| Undo                           | `undo`, followed by a transform read that must match the pre-edit value        | Pending / unverified                |
| Preview                        | `preview_render` to a 64×64 PNG in a temporary directory                       | Pending / unverified                |
| Save-copy and state            | `get_document_state`, `save_document` with `copy: true`, then state comparison | Pending / unverified                |
| Cleanup                        | Close the uniquely named temporary document and remove temporary files         | Pending / unverified                |

Even after this suite passes, the claim is limited to the exact Cinema 4D build, operating system, bridge version, security posture, and foundation path tested. It does **not** promote all 65 tools or any complete tool group.

## Inherited tool catalog

All tools in [TOOLS.md](./TOOLS.md), including advanced modeling, mesh, document I/O outside the foundation save-copy path, node materials, Xpresso, animation, layers, MoGraph, plugin options, render operations, and Python escape hatches, remain inherited/unverified on Cinema 4D 2025.3.2 until a dedicated live test records evidence for them.

`exec_python` is additionally disabled by default and requires `C4D_MCP_ENABLE_EXEC_PYTHON=1` on both the Node and Cinema 4D processes. Creating or editing Python-bearing plugin types requires the independent `C4D_MCP_ENABLE_PYTHON_OPS=1` opt-in on the Cinema 4D side. Enabling either gate changes the security posture and must be recorded with any result.

## Release gate

A release claim requires all of the following evidence from the candidate commit:

1. `npm run build`, `npm test`, and `npm run check` exit `0`.
2. `npm audit --audit-level=high` exits `0`. This gate is satisfied for lockfile commit `d096c18`; rerun it after any dependency or lockfile change.
3. The installer dry-run target is reviewed before an explicit install.
4. `npm run test:live:2025` exits `0` against Cinema 4D 2025.3.2 with no skipped foundation test.
5. The recorded evidence names the commit, Node version, Cinema 4D build, bridge version, relevant environment gates, command exit codes, and skipped-test count.

An ordinary `npm test` can skip bridge-dependent E2E suites and must never be used as the sole live-compatibility signal.
