import { defineTool, textResult } from "./define-tool.js";
import type { ToolSpec } from "./define-tool.js";

export const rsGetCapabilitiesTool: ToolSpec<{}> = defineTool({
  name: "rs_get_capabilities",
  group: "redshift",
  title: "Get Redshift Capabilities",
  description:
    "Report exact Redshift renderer, module, node-space, AOV, light, camera, and render support without mutating the scene.",
  inputShape: {},
  async handler(_args, client) {
    return textResult(await client.request("rs_get_capabilities", {}, 10_000));
  },
});
