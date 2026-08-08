# Male - Clothed FK Sprint Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `Male - Clothed` sprint with FK controls so the character advances 1,500 cm without stretched or twisted limbs.

**Architecture:** Work only in a clean document opened from the pre-sprint backup. Prove the active FK switches and rotation axes with isolated pose tests, create and visually approve a single ten-frame stride, then repeat that validated cycle while adding root translation.

**Tech Stack:** Cinema 4D 2025.3.2, Advanced Biped Character rig, Cinema 4D MCP bridge 0.4.0.

## Global Constraints

- Use Cinema 4D MCP only.
- Source document: `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-backups\male-clothed-before-sprint.c4d`.
- Work at 25 fps over frames 0-60.
- Forward is world `-Z`; final travel is 1,500 cm.
- Do not animate IK leg/arm controls, knee/elbow pole vectors, bind joints, constraints, Character Components, skin, weights, or geometry.
- Keep the rejected `未标题 1` document unchanged for comparison.

---

### Task 1: Prove FK activation and rotation axes

**Files:**

- Inspect: clean Cinema 4D backup document

**Interfaces:**

- Produces: verified FK switch values and flexion components for hips, knees, ankles, shoulders, and elbows.

- [ ] Open a disposable copy of the clean backup and confirm target controls have no tracks.
- [ ] Set leg `IK <-> FK` user data and hand `IK <-> FK` user data to FK.
- [ ] Apply one small rotation to one FK control at a time and render a side preview.
- [ ] Record only axes that bend the limb in the sagittal plane without axial twisting.
- [ ] Close the disposable test document without saving.

### Task 2: Build and verify one ten-frame cycle

**Files:**

- Modify: a fresh clean backup document

**Interfaces:**

- Consumes: verified FK switches and axes from Task 1.
- Produces: a repeatable 0-10 frame cycle with contacts at frames 0, 5, and 10.

- [ ] Set frame range 0-60 and switch all four limbs to FK.
- [ ] Key right/left hip, knee, and ankle rotations at frames 0, 2, 5, 7, and 10 using contact, compression, passing, flight, and opposite-contact poses.
- [ ] Key opposing shoulder and elbow rotations at the same frames.
- [ ] Add restrained torso lean and root bounce.
- [ ] Render following side previews at frames 0, 2, 5, 7, and 10.
- [ ] Reject the cycle if any joint reverses, stretches, twists axially, or intersects the torso.

### Task 3: Extend the validated cycle and add travel

**Files:**

- Modify: the corrected Cinema 4D document

**Interfaces:**

- Consumes: approved ten-frame FK cycle.
- Produces: six cycles over frames 0-60 and 1,500 cm of forward travel.

- [ ] Repeat the validated values every ten frames, alternating limb phases every five frames.
- [ ] Key master/root Z linearly from 0 cm at frame 0 to -1,500 cm at frame 60.
- [ ] Keep vertical bounce within 5 cm peak-to-peak.
- [ ] Render following side previews at every contact frame and representative passing frames.

### Task 4: Final audit and save

**Files:**

- Create: `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-scenes\male-clothed-fast-sprint-fk.c4d`

**Interfaces:**

- Produces: corrected C4D scene and verification evidence.

- [ ] Verify final master travel is exactly 1,500 cm.
- [ ] Verify FK controls contain the expected tracks and all IK/pole-vector controls contain zero tracks.
- [ ] Verify the temporary cameras and diagnostic objects are removed.
- [ ] Restore frame 0, clear selection, and save the corrected scene as a copy.
