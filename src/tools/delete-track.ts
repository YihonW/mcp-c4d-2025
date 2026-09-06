import { z } from "zod";
import { defineTool, textResult } from "./define-tool.js";
import { handleSchema } from "./handle.js";
import { animationSelectorShape, validateAnimationSelector } from "./animation-path.js";

const inputShape = {
  handle: handleSchema.describe("Animated target."),
  ...animationSelectorShape,
};
const input = z.object(inputShape).superRefine(validateAnimationSelector);

export const deleteTrackTool = defineTool({
  name: "delete_track",
  group: "animation",
  title: "Delete Animation Track",
  description:
    "Remove an entire CTrack identified by full path or legacy param_id/component. Returns {removed: bool}.",
  inputShape,
  async handler(args, client) {
    return textResult(await client.request("delete_track", input.parse(args), 10_000));
  },
});
