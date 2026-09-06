import { z } from "zod";
import { defineTool, textResult } from "./define-tool.js";
import { handleSchema } from "./handle.js";
import {
  animationInteger,
  animationSelectorShape,
  validateAnimationSelector,
} from "./animation-path.js";

const inputShape = {
  handle: handleSchema.describe("Entity whose parameter gets the keyframe."),
  ...animationSelectorShape,
  frame: animationInteger.describe("Frame number."),
  value: z
    .union([z.number().finite(), z.boolean()])
    .describe("Value at this frame (rotations in radians)."),
  fps: animationInteger.positive().optional().describe("Time base override (default: doc fps)."),
  interp: z
    .enum(["linear", "spline", "step"])
    .optional()
    .describe('Key interpolation (default "spline").'),
  dtype: z
    .enum(["real", "long", "bool", "vector"])
    .optional()
    .describe("Legacy param_id dtype override; omit with full path."),
};
const input = z.object(inputShape).superRefine(validateAnimationSelector);

export const setKeyframeTool = defineTool({
  name: "set_keyframe",
  group: "crud",
  title: "Set Keyframe",
  description:
    "Create or update one keyframe. Use a full DescID path (including user data) or legacy param_id/component. Supports real/long/bool scalar channels and individual vector components. Creates the CTrack on first use.",
  inputShape,
  async handler(args, client) {
    return textResult(await client.request("set_keyframe", input.parse(args), 15_000));
  },
});
