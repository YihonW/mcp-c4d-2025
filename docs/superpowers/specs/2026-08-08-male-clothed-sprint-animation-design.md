# Male - Clothed Sprint Animation Design

## Goal

Animate the already-rigged `Male - Clothed` character in the active Cinema 4D document as a fast forward sprint. The character must cover real scene distance rather than run in place, while preserving the existing Advanced Biped rig, constraints, skinning, clothing, and materials.

## Verified scene context

- Active document: `未标题 2`.
- Document rate and current range: 25 fps, frames 0-75.
- Character root: `/Male - Clothed`.
- Rig: `/Male - Clothed/Character/Advanced_Biped_rig`.
- The rig exposes `Master_con+`, `Layout_con+`, paired leg/foot/knee IK controls, paired arm IK controls, `Torso_con+`, `Chest_con+`, and `Head_con+`.
- The character root, Character object, and rig root currently have no animation tracks.
- No CMotion object or existing walk/run motion was found.

## Selected approach

Animate the rig's high-level controllers. Do not key the constrained bind joints or edit weight, skin, Pose Morph, XPresso, or Character Component tags.

The alternatives are deliberately rejected:

- CMotion would be quicker but is not configured on this character and gives less control over sprint weight and foot contacts.
- Direct joint animation can fight the IK and constraint network and can destabilize the existing bind.

## Timing and travel

- Keep 25 fps.
- Use frames 0-60, approximately 2.4 seconds.
- Build four full gait cycles, eight foot contacts in total.
- Cover approximately 1,500 cm along the character's current facing direction.
- Ease into speed during the opening frames, then maintain a fast sprint cadence.
- Determine the signed world-forward vector from the evaluated rig/camera views before authoring translation; do not assume a hard-coded world axis.

## Body mechanics

- Establish an aggressive forward lean through the layout/torso controls.
- Add a compact vertical pelvis bounce, small side-to-side weight shift, and opposing chest/pelvis twist.
- Drive each leg through contact, compression, passing, and flight poses with IK foot controls.
- During each stance interval, counter the character-root travel at the planted foot so its world-space position stays nearly fixed.
- Lift the swing foot clearly above the floor, lead with the knee, and extend the lower leg only near the next contact.
- Pitch the foot for heel/toe transition without allowing the sole to penetrate the ground reference.
- Swing the arms strongly opposite the legs; keep elbows bent and avoid hand/body intersections.
- Stabilize the head with smaller counter-rotation than the chest.

## Scene mutation and safety

- Before animation, save a copy of `未标题 2` to `D:\BaiduSyncdisk\AI\mcp_c4d\artifacts\c4d-backups\male-clothed-before-sprint.c4d`. Use Save-As-Copy so the active unsaved document name/path is unchanged.
- Restrict new animation tracks to the character root and verified high-level controls.
- Leave unrelated scene objects, tags, materials, render settings, and hierarchy unchanged.
- Keep arbitrary Python execution disabled.

## Verification

- Read back every new track and its key count.
- Sample the character root and both foot controls at contact, passing, and flight frames.
- Verify the root travels about 1,500 cm in the confirmed forward direction.
- Measure planted-foot world displacement during stance; correct visible sliding.
- Check foot clearance and ground penetration from the evaluated matrices.
- Render preview frames for the first contact, mid-sprint flight, opposite contact, and final pose from side and front views.
- Restore the playhead to frame 0 after verification.

## Acceptance criteria

- The character visibly sprints forward rather than jogging or running in place.
- Four full cycles are readable within frames 0-60.
- The character covers approximately 15 m without sudden root jumps.
- Foot plants do not visibly slide or penetrate the ground.
- Arms oppose the legs, the torso leans and twists, and the head remains comparatively stable.
- The rig, skin, clothes, and existing constraints remain intact.
