import { z } from "zod";
import { defineTool, textResult } from "./define-tool.js";
import { handleSchema } from "./handle.js";
import {
  animationInteger,
  animationSelectorShape,
  validateAnimationSelector,
} from "./animation-path.js";

const frameNumber = z.number().finite().min(-1_000_000).max(1_000_000);
const keyIndex = z.number().int().min(0).max(999);
const commonShape = {
  document_name: z
    .string()
    .min(1)
    .refine((name) => name.trim().length > 0, "Document name must not be blank")
    .describe(
      "Exact active document name. A mismatch is rejected; this tool never switches documents.",
    ),
  handle: handleSchema.describe("Entity with an existing REAL value track."),
  ...animationSelectorShape,
  fps: animationInteger.positive().optional().describe("Time base, default document FPS."),
};

const getShape = {
  ...commonShape,
  sample_frames: z
    .array(frameNumber)
    .min(1)
    .max(300)
    .optional()
    .describe("Optional sample positions, including subframes. Does not move document time."),
};
const getInput = z.strictObject(getShape).superRefine(validateAnimationSelector);

export const getFcurveTool = defineTool({
  name: "get_fcurve",
  group: "animation",
  title: "Read F-Curve",
  description:
    "Read an existing REAL F-Curve: stable key indices for this snapshot, precise frame times, values, interpolation, tangent offsets and pre/post extrapolation. Optionally sample the track. At most 1000 keys. Does not create a track/curve or change document time. Not a scene/constraint evaluation or character-animation reader.",
  inputShape: getShape,
  async handler(args, client) {
    return textResult(await client.request("get_fcurve", getInput.parse(args), 10_000));
  },
});

const edit = z
  .strictObject({
    key_index: keyIndex.describe(
      "Index from a fresh get_fcurve result, before any edits in this call.",
    ),
    value: z.number().finite().optional().describe("New key value, rotations in radians."),
    interp: z.enum(["linear", "spline", "step"]).optional(),
    tangent_mode: z.enum(["auto", "manual"]).optional(),
    left: z
      .strictObject({ dt_frames: frameNumber.negative(), dv: z.number().finite() })
      .optional()
      .describe("Left tangent offsets relative to the key; requires tangent_mode=manual."),
    right: z
      .strictObject({ dt_frames: frameNumber.positive(), dv: z.number().finite() })
      .optional()
      .describe("Right tangent offsets relative to the key; requires tangent_mode=manual."),
  })
  .superRefine((value, ctx) => {
    if (
      value.value === undefined &&
      value.interp === undefined &&
      value.tangent_mode === undefined &&
      value.left === undefined &&
      value.right === undefined
    ) {
      ctx.addIssue({ code: "custom", message: "Each edit must change at least one field" });
    }
    if ((value.left || value.right) && value.tangent_mode !== "manual") {
      ctx.addIssue({ code: "custom", message: "Explicit tangents require tangent_mode=manual" });
    }
  });
const editShape = {
  ...commonShape,
  edits: z
    .array(edit)
    .min(1)
    .max(1000)
    .refine((edits) => new Set(edits.map((item) => item.key_index)).size === edits.length, {
      message: "Duplicate key_index entries are not allowed",
    }),
};
const editInput = z.strictObject(editShape).superRefine(validateAnimationSelector);

export const editFcurveKeysTool = defineTool({
  name: "edit_fcurve_keys",
  group: "animation",
  title: "Edit F-Curve Keys",
  description:
    "Edit existing REAL keys by snapshot index: values, linear/spline/step interpolation, automatic or manual tangents. Left/right are signed offsets, not absolute control-point positions. Manual takeover splits handles and disables automatic/clamp/auto-weight/overshoot/tangent-lock options; key time/value locks are respected. Read get_fcurve first and avoid simultaneous scene edits. Preflights the complete batch before a single undo-grouped track update. Does not create keys or edit coupled XYZ/time tracks.",
  inputShape: editShape,
  async handler(args, client) {
    return textResult(await client.request("edit_fcurve_keys", editInput.parse(args), 15_000));
  },
});

const transformShape = {
  ...commonShape,
  key_indices: z
    .array(keyIndex)
    .min(1)
    .max(1000)
    .refine(
      (indices) => new Set(indices).size === indices.length,
      "Duplicate indices are not allowed",
    )
    .optional()
    .describe("Snapshot indices to transform; omit to transform all keys (at most 1000)."),
  time_scale: z
    .number()
    .finite()
    .positive()
    .max(1_000_000)
    .optional()
    .describe("Positive time scale, default 1. Time reversal is not supported."),
  time_offset_frames: frameNumber.optional().describe("Time shift after scaling, default 0."),
  pivot_frame: frameNumber.optional().describe("Time scaling pivot, default 0."),
  value_scale: z
    .number()
    .finite()
    .optional()
    .describe("Value scale, default 1. Zero and negative values are allowed."),
  value_offset: z.number().finite().optional().describe("Value shift after scaling, default 0."),
  value_pivot: z.number().finite().optional().describe("Value scaling pivot, default 0."),
};
const transformInput = z
  .strictObject(transformShape)
  .superRefine(validateAnimationSelector)
  .superRefine((value, ctx) => {
    if (
      value.time_scale === undefined &&
      value.time_offset_frames === undefined &&
      value.pivot_frame === undefined &&
      value.value_scale === undefined &&
      value.value_offset === undefined &&
      value.value_pivot === undefined
    ) {
      ctx.addIssue({ code: "custom", message: "Provide at least one transform field" });
    }
  });

export const transformFcurveTool = defineTool({
  name: "transform_fcurve",
  group: "animation",
  title: "Transform F-Curve",
  description:
    "Retime/scale selected or all REAL keys. Manual tangents scale with the keys; AUTO remains automatic and is recalculated by Cinema 4D. New time = pivot + (old time - pivot) * scale + offset; value uses the analogous formula. Supports subframes, rejects collisions with all keys and out-of-range results before writing. Read the curve again afterward because sorted key indices can change. No time reversal or cross-track bake.",
  inputShape: transformShape,
  async handler(args, client) {
    return textResult(await client.request("transform_fcurve", transformInput.parse(args), 15_000));
  },
});

const extrapolation = z.enum(["off", "constant", "linear", "repeat", "offset_repeat", "oscillate"]);
const extrapolationShape = {
  ...commonShape,
  before: extrapolation.optional().describe("Behavior before the first key; omit to preserve."),
  after: extrapolation.optional().describe("Behavior after the last key; omit to preserve."),
};
const extrapolationInput = z
  .strictObject(extrapolationShape)
  .superRefine(validateAnimationSelector)
  .superRefine((value, ctx) => {
    if (value.before === undefined && value.after === undefined) {
      ctx.addIssue({ code: "custom", message: "Provide before and/or after" });
    }
  });

export const setTrackExtrapolationTool = defineTool({
  name: "set_track_extrapolation",
  group: "animation",
  title: "Set Track Extrapolation",
  description:
    "Set pre/post behavior for an existing REAL track: off, hold constant, continue (linear), repeat, offset repeat or oscillate. Omitted side is preserved. Does not duplicate keys, extend the document frame range or bake loops.",
  inputShape: extrapolationShape,
  async handler(args, client) {
    return textResult(
      await client.request("set_track_extrapolation", extrapolationInput.parse(args), 15_000),
    );
  },
});
