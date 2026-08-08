import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

export const rsListAovsTool = defineTool({
  name: "rs_list_aovs",
  group: "redshift",
  title: "List Redshift AOVs",
  description: "List Redshift AOVs from the active or named RenderData.",
  inputShape: {
    document_name: z.string().trim().min(1).optional().describe("Open document name."),
    render_data_name: z.string().trim().min(1).optional().describe("RenderData name."),
  },
  async handler(args, client) {
    return textResult(await client.request("rs_list_aovs", args, 10_000));
  },
});
