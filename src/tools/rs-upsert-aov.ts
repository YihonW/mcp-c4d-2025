import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

const primitive = z.union([z.boolean(), z.number().finite(), z.string()]);

export const rsUpsertAovInputShape = {
  document_name: z.string().trim().min(1).optional().describe("Open document name."),
  render_data_name: z.string().trim().min(1).optional().describe("RenderData name."),
  type: z.union([z.string().trim().min(1), z.number().int()]),
  name: z.string().trim().min(1).describe("AOV name."),
  enabled: z.boolean().optional(),
  multipass_enabled: z.boolean().optional(),
  direct_file_enabled: z.boolean().optional(),
  direct_file_path: z.string().trim().min(1).optional().describe("Absolute output path."),
  params: z.record(z.string(), primitive).optional(),
};

export const rsUpsertAovInput = z.object(rsUpsertAovInputShape).superRefine((value, ctx) => {
  if (value.direct_file_enabled === true && value.direct_file_path === undefined) {
    ctx.addIssue({
      code: "custom",
      path: ["direct_file_path"],
      message: "direct_file_path is required when direct_file_enabled is true",
    });
  }
});

export const rsUpsertAovTool = defineTool({
  name: "rs_upsert_aov",
  group: "redshift",
  title: "Create or Update Redshift AOV",
  description: "Create or update one exact Redshift AOV type/name pair.",
  inputShape: rsUpsertAovInputShape,
  async handler(args, client) {
    return textResult(await client.request("rs_upsert_aov", rsUpsertAovInput.parse(args), 30_000));
  },
});
