# Basketball Bounce Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and verify a five-second realistic basketball bounce in the active Cinema 4D document through MCP only.

**Architecture:** Use the bridge's typed entity, document, parameter, and keyframe operations. Build simple scene primitives, author deterministic transform keys, and verify by reading tracks, sampling transforms, and rendering bounded previews.

**Tech Stack:** Cinema 4D 2025.3.2, Cinema 4D MCP bridge 0.4.0, MCP typed tools.

## Global Constraints

- Work in the current active document and do not overwrite a saved scene.
- Use MCP only; do not automate the Cinema 4D user interface.
- Keep 25 fps and set the range to frames 0-125.
- Keep arbitrary Python execution disabled.

---

### Task 1: Create the scene foundation

**Files:**

- Modify: active Cinema 4D document `未标题 1`

**Interfaces:**

- Produces: object handles for `篮球` and `地面`.
- Produces: document range 0-125 at 25 fps.

- [ ] **Step 1: Confirm the bridge and active document**

Call `ping`, `get_document_state`, and `list_entities(kind="object")`.

Expected: Cinema 4D 2025.3.2 is reachable and the active document is `未标题 1`.

- [ ] **Step 2: Set the document range**

Call `set_document({fps:25, frame_start:0, frame_end:125})`.

Expected: `get_document_state` returns frames 0-125 at 25 fps.

- [ ] **Step 3: Create the ball and floor**

Create a sphere named `篮球` at `[0,220,0]` with radius 12 cm, and a plane named `地面` centered at `[0,0,0]` large enough to frame the motion.

Expected: `list_entities(kind="object")` returns exactly those new scene objects.

### Task 2: Author the bounce

**Files:**

- Modify: animation tracks on `篮球` in `未标题 1`

**Interfaces:**

- Consumes: stable `篮球` object handle from Task 1.
- Produces: Y-position, X/Y/Z-scale, and rotation tracks.

- [ ] **Step 1: Add vertical motion keys**

Sample the accelerating initial fall on frames 0-16, then sample parabolic rebounds between contact frames 16/41/58/71/80/87/92/96. Use decreasing peak heights of approximately 112/58/31/16/8/4/2 cm above the resting center, linear interpolation, and a stationary hold through frame 125.

Expected: `get_keyframes` returns frame-sampled parabolic arcs, declining apex heights, and decreasing contact intervals without spline overshoot.

- [ ] **Step 2: Add impact deformation keys**

At each contact frame 16/41/58/71/80/87/92, add a short anticipation key, an impact scale near `[1.10,0.82,1.10]` with decreasing strength, and a recovery key two frames later at `[1,1,1]`. At an impact with Y scale `s`, set the center to `12*s` cm so the deformed ball remains in contact with the floor.

Expected: every impact has one brief squash and the final scale is `[1,1,1]`.

- [ ] **Step 3: Add subtle rotation**

Animate one rotation component from 0 to roughly 2.4 radians by frame 96, then hold through frame 125.

Expected: rotation stops when the ball settles.

### Task 3: Verify the finished scene

**Files:**

- Inspect: active Cinema 4D document `未标题 1`

**Interfaces:**

- Consumes: completed document and animation tracks.
- Produces: read-back evidence and three preview images.

- [ ] **Step 1: Read back tracks and keys**

Call `list_tracks` and `get_keyframes` for position, scale, and rotation.

Expected: all planned tracks exist, and frames 96-125 remain stationary.

- [ ] **Step 2: Sample critical frames**

Sample frames 0, 16, 28, 41, 58, 71, 92, 96, and 125.

Expected: the deformed ball's world-space lower boundary is Y=0 at contact, no sample penetrates the floor, and the final transform is stable.

- [ ] **Step 3: Render previews**

Render previews at frames 16, 64, and 125 with the MCP preview renderer.

Expected: the ball visibly contacts the floor, rebounds lower in the middle, and rests undeformed at the end.
