import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

export const rsRemoveAovInputShape = {
  document_name: z.string().trim().min(1).optional().describe("Open document name."),
  render_data_name: z.string().trim().min(1).optional().describe("RenderData name."),
  index: z.number().int().nonnegative(),
  expected_name: z.string().trim().min(1),
  expected_type: z.union([z.string().trim().min(1), z.number().int()]),
};

export const rsRemoveAovInput = z.object(rsRemoveAovInputShape);

export const rsRemoveAovTool = defineTool({
  name: "rs_remove_aov",
  group: "redshift",
  title: "Remove Redshift AOV",
  description: "Remove one indexed Redshift AOV when its expected name and type still match.",
  inputShape: rsRemoveAovInputShape,
  async handler(args, client) {
    return textResult(await client.request("rs_remove_aov", rsRemoveAovInput.parse(args), 30_000));
  },
});
