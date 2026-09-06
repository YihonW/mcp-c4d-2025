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
  handle: handleSchema.describe("Animated entity."),
  ...animationSelectorShape,
  start_frame: animationInteger.optional().describe("Inclusive lower frame bound."),
  end_frame: animationInteger.optional().describe("Inclusive upper frame bound."),
  fps: animationInteger
    .positive()
    .optional()
    .describe("Override for BaseTime to frame conversion."),
};
const input = z
  .object(inputShape)
  .superRefine(validateAnimationSelector)
  .superRefine(validateAnimationRange);

export const getKeyframesTool = defineTool({
  name: "get_keyframes",
  group: "animation",
  title: "Get Keyframes",
  description:
    "Read keys using a full path from list_tracks or legacy param_id/component. Returns [{frame, value, interp}]. Optional start_frame/end_frame clip the range inclusively.",
  inputShape,
  async handler(args, client) {
    return textResult(await client.request("get_keyframes", input.parse(args), 10_000));
  },
});
