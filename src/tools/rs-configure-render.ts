import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

const primitive = z.union([z.boolean(), z.number().finite(), z.string()]);

export const rsConfigureRenderInputShape = {
  document_name: z.string().trim().min(1).optional().describe("Open document name."),
  name: z.string().trim().min(1).describe("RenderData name."),
  update_if_exists: z.boolean().optional(),
  make_active: z.boolean().optional(),
  width: z.number().int().positive().optional(),
  height: z.number().int().positive().optional(),
  frame: z.number().int().optional(),
  output_format: z.enum(["png", "jpg", "tif", "exr"]).optional(),
  beauty_path: z.string().trim().min(1).optional(),
  multipass_path: z.string().trim().min(1).optional(),
  redshift_params: z.record(z.string(), primitive).optional(),
};

export const rsConfigureRenderInput = z.object(rsConfigureRenderInputShape);

export const rsConfigureRenderTool = defineTool({
  name: "rs_configure_render",
  group: "redshift",
  title: "Configure Redshift RenderData",
  description: "Create or update a validated Redshift RenderData without implicit activation.",
  inputShape: rsConfigureRenderInputShape,
  async handler(args, client) {
    return textResult(
      await client.request("rs_configure_render", rsConfigureRenderInput.parse(args), 30_000),
    );
  },
});
