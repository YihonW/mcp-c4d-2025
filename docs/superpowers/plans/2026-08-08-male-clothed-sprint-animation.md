# Male - Clothed Sprint Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Animate the existing `Male - Clothed` Advanced Biped rig as a fast 15 m forward sprint over frames 0-60 in the active Cinema 4D document.

**Architecture:** Translate the character root along its verified facing direction while posing only high-level Advanced Biped controls. Convert desired world-space foot plants into controller-local positions so the planted foot stays fixed while the root advances; use torso, chest, head, arm, and elbow controls for the upper-body sprint mechanics.

**Tech Stack:** Cinema 4D 2025.3.2, Cinema 4D MCP bridge 0.4.0, typed entity/keyframe/sample/preview MCP tools.

## Global Constraints

- Active document: `未标题 1` at 25 fps (re-identified after Cinema 4D collapsed the earlier document list).
- Animate frames 0-60; leave the document maximum at 75 unless verification requires only a play-range change.
- Character root: `/Male - Clothed`.
- Do not key bind joints or edit Character Component, constraint, IK, XPresso, skin, weight, material, or Pose Morph data.
- Use MCP tools only; do not automate the Cinema 4D user interface.
- Keep arbitrary Python execution disabled.
- Save a copy before mutation to `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-backups\male-clothed-before-sprint.c4d`.

## Controller paths

```text
ROOT=/Male - Clothed
MASTER=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+
LAYOUT=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+
TORSO=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/Torso_con+
CHEST=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/Torso_con+/Chest_con+
HEAD=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/Head_algn/Head_con+
R_FOOT=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/R_IK_Leg_con+
L_FOOT=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/L_IK_Leg_con+
R_KNEE=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/R_Knee_algn/R_Knee_con+
L_KNEE=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/L_Knee_algn/L_Knee_con+
R_ARM=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/R_IK_Arm_con+
L_ARM=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/L_IK_Arm_con+
R_ELBOW=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/R_Elbow_algn/R_Elbow_con+
L_ELBOW=/Male - Clothed/Character/Advanced_Biped_rig/Root_null/Master_con+/Layout_con+/L_Elbow_algn/L_Elbow_con+
```

---

### Task 1: Backup, baseline, and forward-axis proof

**Files:**

- Create: `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-backups\male-clothed-before-sprint.c4d`
- Modify later: active Cinema 4D document `未标题 1`

**Interfaces:**

- Produces: backup copy, baseline transform map for every controller path, ground height, and normalized world vectors `F` (forward), `U=[0,1,0]`, and `R=normalize(cross(U,F))`.
- Produces: `parentInverse`, the inverse affine matrix of `LAYOUT` at frame 0 for converting desired world offsets into controller-local offsets.

- [ ] **Step 1: Verify the target and clean animation baseline**

Call `ping`, `get_document_state`, `get_selection`, and `list_tracks` for `ROOT`, `MASTER`, `LAYOUT`, both feet, both arms, `TORSO`, `CHEST`, and `HEAD`.

Expected: Cinema 4D 2025.3.2 is reachable, `未标题 1` is active, `Male - Clothed` exists, and the listed controls have no animation tracks.

- [ ] **Step 2: Create the backup directory and save a copy**

Create only `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-backups`, then call:

```json
{
  "path": "D:\\BaiduSyncdisk\\AI\\mcp_c4d\\artifacts\\c4d-backups\\male-clothed-before-sprint.c4d",
  "format": "c4d",
  "copy": true
}
```

Expected: the file exists and `get_document_state` still reports document name `未标题 1` with an empty path.

- [ ] **Step 3: Capture baseline matrices**

Set frame 0 and call `sample_transform(format="matrix", space="global")` for `ROOT`, `LAYOUT`, `TORSO`, `CHEST`, `HEAD`, both feet, knees, arms, and elbows.

Expected: every handle resolves. Record the controller-local position/rotation values with `list_entities(include_params=[903,904,905])` before writing keys.

- [ ] **Step 4: Determine the facing direction**

Render unselected front and right previews at frame 0. Project `LAYOUT`'s local Z basis onto the XZ plane; use `+Z` when that arrow points through the character's chest and `-Z` when it points through the back. Normalize the selected signed projection as `F`.

Expected: the visible face and toe pivots confirm forward as world `-Z`; record `F=[0,0,-1]`.

### Task 2: Root travel and torso mechanics

**Files:**

- Modify: animation tracks on `MASTER`, `TORSO`, `CHEST`, and `HEAD` in `未标题 1`

**Interfaces:**

- Consumes: baseline transforms and `F` from Task 1.
- Produces: root distance curve `d(frame)` and upper-body motion keys.

- [ ] **Step 1: Prove the unanimated root does not travel**

Sample `MASTER` at frames `[0,8,15,23,30,38,45,53,60]`.

Expected RED result: every root sample has the same world position, so forward distance at frame 60 is 0 cm instead of 1,500 cm.

- [ ] **Step 2: Key the root distance curve**

Use linear interpolation for the master Z track with these distances along verified `F=-Z`:

```text
frame:     0    4    8    15   23   30   38   45   53   60
distance:  0   40  130   310  500  700  900 1100 1300 1500 cm
```

For each frame, write `MASTER.position = master0 + F * distance`; add a separate small vertical sprint-bounce track.

- [ ] **Step 3: Verify root travel**

Sample the same frames again.

Expected GREEN result: projected distance is monotonic, has no backward jump, and frame 60 lies within 1 cm of 1,500 cm.

- [ ] **Step 4: Add torso, chest, and head mechanics**

At sprint contacts `[0,8,15,23,30,38,45,53,60]`, alternate chest heading twist by `±0.10` rad, set torso pitch toward `F` to `0.24` rad with the sign confirmed by the side preview, and add torso local Y offsets `[-2,+3,-3,+3,-3,+3,-3,+3,-2]` cm. Counter-rotate the head pitch by 35% and heading by 40% of the chest value. Use spline interpolation.

Expected: a side preview shows forward lean; front previews show alternating shoulder twist without head whipping.

### Task 3: Lower-body sprint cycle and planted-foot lock

**Files:**

- Modify: animation tracks on `R_FOOT`, `L_FOOT`, `R_KNEE`, and `L_KNEE` in `未标题 1`

**Interfaces:**

- Consumes: `F`, `R`, `U`, `parentInverse`, baseline controller transforms, and root distance curve.
- Produces: four gait cycles with foot-contact sequences `R=[0,15,30,45,60]` and `L=[-7,8,23,38,53,68]` clipped to frames 0-60.

- [ ] **Step 1: Demonstrate root-only foot sliding**

With only Task 2 keys present, sample both foot controls at frames 0-4 after the right contact and frames 8-12 after the left contact.

Expected RED result: each foot advances with the root during its supposed stance interval; projected stance displacement exceeds 1 cm.

- [ ] **Step 2: Define the world-space foot targets**

For each same-foot interval `[c,c+15]`, use the contact point `plant(c)` and the following poses:

```text
c+0 contact:     plant(c), ground height
c+2 compression: plant(c), ground height
c+4 toe-off:     plant(c) + F*15 + U*22
c+8 passing:     plant(c) + F*187.5 + U*55
c+12 flight:     plant(c+15) - F*55 + U*35
c+15 contact:    plant(c+15), ground height
```

Successive same-foot plants are 375 cm apart. Preserve the baseline left/right lateral separation by deriving each `plant(0)` from that foot's frame-0 global matrix.

- [ ] **Step 3: Convert targets and key the foot controls**

At every listed pose, subtract the root world translation at that frame, transform the remaining world offset by `parentInverse`, add the controller's baseline local position, and key parameter 903 X/Y/Z with spline interpolation. Add foot pitch keys of `0`, `-0.22`, `+0.32`, `+0.12`, and `0` rad through contact/toe-off/passing/flight/contact, choosing the sign that raises the toe in the side preview.

- [ ] **Step 4: Key knee aim offsets**

For each foot phase, move the matching knee controller along `F` by `[+20,+35,+55,+75,+20]` cm and upward by `[0,-5,+12,+8,0]` cm relative to baseline, converted through its parent orientation. Keep the knee on its original lateral side.

- [ ] **Step 5: Verify foot lock and clearance**

Sample foot matrices on every keyed frame. During `c..c+2`, projected stance displacement must be at most 1 cm. Swing-foot height must be at least 20 cm at toe-off and 45 cm at passing. No evaluated foot-control origin may fall below its baseline ground height by more than 0.5 cm.

If a check fails, adjust only the failing controller/key and repeat this step.

### Task 4: Opposing arm drive

**Files:**

- Modify: animation tracks on `R_ARM`, `L_ARM`, `R_ELBOW`, and `L_ELBOW` in `未标题 1`

**Interfaces:**

- Consumes: `F`, `R`, `U`, controller baselines, and the contact frame list.
- Produces: arms that oppose the legs and remain clear of the torso.

- [ ] **Step 1: Prove the arms are static**

Sample both arm and elbow controls at contact frames `[0,8,15,23,30,38,45,53,60]`.

Expected RED result: every arm control remains at its baseline despite the animated root and legs.

- [ ] **Step 2: Key alternating arm targets**

When the right foot contacts, target the left arm `F*45 + U*10` from baseline and the right arm `F*-50 + U*-5`; swap the signs at the left-foot contacts. Add `R*±8` cm outward clearance. At the midpoint between contacts, use 40% of the next contact offset to avoid mechanical straight-line crossing. Convert offsets through the `LAYOUT` parent orientation and use spline interpolation.

- [ ] **Step 3: Key elbow aims**

Offset each elbow control outward by 18 cm along its existing lateral side and backward by 12 cm relative to its matching wrist target, alternating with the arms. Preserve the controller's baseline height plus a `+5` cm lift.

- [ ] **Step 4: Verify opposition and intersections**

Sample all arm controls at contacts and midpoints. The forward projection of each arm must have the opposite sign to the same-side foot swing. Front and side previews must show bent elbows and no hand/torso intersections.

### Task 5: Final verification and handoff

**Files:**

- Inspect: active Cinema 4D document `未标题 1`
- Retain: `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-backups\male-clothed-before-sprint.c4d`

**Interfaces:**

- Consumes: all animation tracks from Tasks 2-4.
- Produces: read-back evidence, clean previews, and a frame-0 handoff state.

- [ ] **Step 1: Audit changed entities**

Run `list_tracks` for every target controller and verify that no bind joint, mesh, material, tag, Character object, or unrelated object gained a track.

Expected: tracks exist only on `ROOT`, `TORSO`, `CHEST`, `HEAD`, both feet, knees, arms, and elbows.

- [ ] **Step 2: Sample critical frames**

Sample root, feet, torso, chest, head, arms, and elbows at frames `[0,4,8,12,15,19,23,27,30,34,38,42,45,49,53,57,60]`.

Expected: root distance is monotonic to 1,500 cm; planted feet satisfy the 1 cm tolerance; swing feet clear the ground; head rotation amplitude remains smaller than chest rotation.

- [ ] **Step 3: Render clean previews**

Clear selection and render front and side previews at frames `[0,8,15,23,30,38,45,53,60]`.

Expected: the sequence reads as a fast sprint with forward lean, aerial phases, long strides, opposing arms, and no obvious sliding or body intersection.

- [ ] **Step 4: Restore the handoff state**

Set frame 0, clear selection, and re-read `get_document_state` plus frame-0 controller parameters after all samplers finish.

Expected: playhead and evaluated cache both match frame 0; the active document remains `未标题 1` and unsaved.
