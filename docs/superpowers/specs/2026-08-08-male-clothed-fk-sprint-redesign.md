# Male - Clothed FK Sprint Redesign

## Goal

Replace the distorted IK sprint with a normal-looking forward sprint on the clean `Male - Clothed` Advanced Biped rig.

## Root cause addressed

The rejected version drove IK end effectors and pole vectors directly. The control targets were numerically correct, but the solver stretched and twisted the skinned limbs. The redesign does not reuse any rejected animation tracks.

## Motion design

- Work from `male-clothed-before-sprint.c4d` at 25 fps.
- Animate frames 0-60 and move 1,500 cm along world `-Z`.
- Use twelve alternating contacts, one every five frames. Each step advances about 125 cm; each same-foot stride advances 250 cm.
- Switch arms and legs to FK, then animate only hip, knee, ankle, shoulder, elbow, torso, chest, head, and master/root controls.
- Keep knee and elbow bends anatomically consistent; never translate IK end effectors or pole-vector controls.
- Use about 10-12 degrees of forward torso lean, small vertical root motion, and opposing arms.

## Verification gates

1. Determine each FK flexion axis with isolated small-angle tests on a disposable clean copy.
2. Build only frames 0-10 first and inspect frames 0, 2, 5, 7, and 10 from a following side camera.
3. Extend to frame 60 only after the test cycle has fixed-length limbs, forward knees, bent elbows, and no visible mesh twisting.
4. Audit that the rejected IK and pole-vector controllers have no tracks in the corrected scene.
