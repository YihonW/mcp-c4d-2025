# 0.4.0 workflow validation — 2026-09-06

## Candidate and runtime

- Installed bridge source: `81e319d`. Subsequent documentation/test-assertion changes do not change installed Python source.
- Windows x64; Cinema 4D `2025302` / `2025.3.2`; Python `3.11.4`; Node.js `24.18.0`; bridge `0.4.0`; MCP package `0.4.0`.
- Loopback and token authentication enabled. Arbitrary Python and Python-bearing operation gates were not enabled.
- 79 registered source tools, 78 exposed by default. Tool count is not a universal support claim.

## Offline verification

- Python: **140 passed** (`python -m unittest discover -s tests/python`).
- TypeScript: **111 passed**, 12 files (`npm test`, unit tests only).
- `npm run check`: exit 0, no lint warnings; typecheck, formatting, Ruff, build and generated tool documentation passed.
- `npm audit --audit-level=high`: zero vulnerabilities.
- CI now runs the offline Python and TypeScript regressions. It never starts live C4D tests.

The first GitHub CI run exposed an inherited test-platform mismatch: eleven Windows installer CLI fixture tests were executed under Linux and rejected its non-drive-letter temporary paths. CI was changed to a Linux/Windows matrix; only the Windows filesystem CLI suite is explicitly skipped on non-Windows runners. The pure path-policy tests and all other unit tests run on both, and Windows still runs all 111 tests. This does not change the installer or installed C4D code.

New regressions cover full animation paths, selector/range validation, BOOL data keys, interpolation enum zero, undo recording, reference preflight, editable-object hierarchy preservation, frame/state restoration, cancellation races, PNG chunk CRC validation and conservative transport-failure handling.

## Live results

All times are Asia/Shanghai; durations are total test-run durations.

| Command                           | Start time | Outcome                     | Duration |
| --------------------------------- | ---------- | --------------------------- | -------- |
| `npm run test:live:workflow:2025` | 19:37:45   | 1 passed, 0 skipped, exit 0 | 18.56 s  |
| `npm run test:live:2025`          | 19:39:54   | 1 passed, 0 skipped, exit 0 | 3.42 s   |
| `npm run test:live:redshift:2025` | 19:39:58   | 1 passed, 0 skipped, exit 0 | 6.22 s   |

The first workflow attempt at 19:37:06 stopped at a test assertion: `MatrixToHPB` returned `2*pi - 0.35` for the expected `-0.35` rotation. The values describe the same rotation. The assertion was corrected to compare signed angular difference modulo `2*pi`; it still checks the intermediate linear value. No production-code change or plugin reinstall was needed. That attempt's sole test document was closed before the corrected run.

### Newly verified workflow boundary

One uniquely named, initially inactive test document contained:

1. Two Null pivots and two cube segments in a two-level parent hierarchy. Each cube was independently made editable; its parent path, eight points, six polygons and segment length were read back.
2. Direct rotation keys at frames 0, 12 and 24. Local samples at 0/6/12/24 verified interpolation; the child segment's world position changed as expected.
3. A separate REAL user-data parameter: complete DescID static write/read and three keyframes written/read by `path`.
4. A separate link user-data parameter: object-reference write/read; rejection of a nonexistent target without clearing the previous reference.
5. Redshift PBR material assignment, Area and textured Dome lights, a named camera selected for rendering, and inactive 128×128 PNG RenderData with no AOVs.
6. `rs_render_sequence` output at frames 0/2/4/6/8/10/12. All seven files passed PNG structure/CRC, size/dimension and SHA-256 checks; all seven hashes differed. Status and final manifest agreed, and the document state was restored.
7. A saved `.c4d` copy, verified non-empty without changing the active document's path/name.

The first and last PNGs were visually inspected: the two-segment shape moves from approximately straight to bent. These are tiny, brightly lit technical smoke renders, not a polished lighting/material-quality acceptance test.

This is **rigid parent-hierarchy animation**, not a joint skeleton, skinning, IK solver or controller-driven Xpresso rig. The user-data tests are independent parameter tests, not proof that user-data drives those joints.

### Still not promoted

- BOOL/user-data vector animation and keyframe undo are offline-tested, not newly live-verified by this workflow.
- Sequence cancellation/resume and failure paths are offline-tested; only successful seven-frame sequence execution is live-verified.
- Production-length/high-resolution rendering, AOV sequences, cross-process recovery, unbaked simulations, high-bit-depth/alpha output and arbitrary third-party plugins remain unverified.
- The workflow does not promote character skinning/weights, IK/FK, Pose Morph, motion retargeting, UV workflows, all modeling commands or every inherited tool.
- Explicit-frame suppression of inherited automatic save paths is offline-tested; this live RenderData did not deliberately enable those inherited paths.

## Session safety and installation

The original project was saved as a separate checkpoint before a normal save/quit. No forced process termination or hot reload was used. The installer was invoked only after confirming no Cinema 4D process remained; the destination was explicitly selected when multiple preference folders were detected.

All 70 previous plugin files matched their external backup by path and SHA-256. All 70 installed files matched the source before startup. The backup directory is `cinema4d_mcp_bridge.backup-2026-09-06T11-34-29.397Z`, outside `plugins`.

The original empty project received one uniquely named temporary Null to prevent Cinema 4D's automatic blank-document disposal. Four temporary documents were created sequentially across the failed assertion attempt and the three successful suites; at most one test document was open at once. Every test document was closed. The temporary Null was removed, the original empty project was saved, and Cinema 4D was left running.

Local outputs are retained under the ignored `artifacts/workflow-0.4.0-20260906/` folder for audit only. Its saved scene/manifest retain the original temporary texture/output paths and are not a portable asset package. User projects, backups, generated outputs and `.env` files are excluded from publication. No npm/MCP Registry release is implied by uploading the source to GitHub.
