import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

export const rsClearAovsInputShape = {
  document_name: z.string().trim().min(1).describe("Unique open document name."),
  render_data_name: z.string().trim().min(1).optional().describe("RenderData name."),
  force: z.literal(true),
};

export const rsClearAovsInput = z.object(rsClearAovsInputShape);

export const rsClearAovsTool = defineTool({
  name: "rs_clear_aovs",
  group: "redshift",
  title: "Clear Redshift AOVs",
  description: "Clear all Redshift AOVs from one explicitly named document.",
  inputShape: rsClearAovsInputShape,
  async handler(args, client) {
    return textResult(await client.request("rs_clear_aovs", rsClearAovsInput.parse(args), 30_000));
  },
});
