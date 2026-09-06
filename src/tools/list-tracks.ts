import { defineTool, textResult } from "./define-tool.js";
import { handleSchema } from "./handle.js";

export const listTracksTool = defineTool({
  name: "list_tracks",
  group: "animation",
  title: "List Animation Tracks",
  description:
    "Enumerate CTracks. Each entry includes name, full path ([[id,dtype,creator],...]), legacy param_id/component, dtype and key_count. Pass path alone with the entity handle to get/set/delete keyframes or delete_track. Vector channels have separate entries per component.",
  inputShape: {
    handle: handleSchema.describe("Entity whose animation tracks to enumerate."),
  },
  async handler(args, client) {
    return textResult(await client.request("list_tracks", args, 10_000));
  },
});
