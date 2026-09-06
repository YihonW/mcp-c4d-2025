import { z } from "zod";
import { defineTool, textResult } from "./define-tool.js";
import { handleSchema } from "./handle.js";
import {
  animationInteger,
  animationSelectorShape,
  validateAnimationSelector,
  validateAnimationRange,
} from "./animation-path.js";

const inputShape = {
  handle: handleSchema.describe("Animated target."),
  ...animationSelectorShape,
  frame: animationInteger.optional().describe("Single frame to remove."),
  start_frame: animationInteger.optional().describe("Inclusive lower bound."),
  end_frame: animationInteger.optional().describe("Inclusive upper bound."),
  fps: animationInteger.positive().optional().describe("Override for BaseTime conversion."),
};
const input = z
  .object(inputShape)
  .superRefine(validateAnimationSelector)
  .superRefine(validateAnimationRange)
  .superRefine((value, ctx) => {
    if (
      value.frame !== undefined &&
      (value.start_frame !== undefined || value.end_frame !== undefined)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["frame"],
        message: "frame is exclusive with start_frame/end_frame",
      });
    }
  });

export const deleteKeyframeTool = defineTool({
  name: "delete_keyframe",
  group: "animation",
  title: "Delete Keyframe",
  description:
    "Remove keys selected by full path or legacy param_id/component. Pass an integer frame for an exact-time key, or integer start_frame/end_frame for an inclusive range; fractional key times are not rounded into the selection. Omitting all frame bounds deletes every key on that track. Returns {removed, track}.",
  inputShape,
  async handler(args, client) {
    return textResult(await client.request("delete_keyframe", input.parse(args), 10_000));
  },
});
