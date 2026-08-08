import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

export const rsRenderInputShape = {
  document_name: z.string().trim().min(1).describe("Unique open document name."),
  render_data_name: z.string().trim().min(1).describe("Unique Redshift RenderData name."),
  output_path: z.string().trim().min(1).describe("Absolute Beauty output path."),
  force: z.literal(true),
  overwrite: z.boolean().optional(),
};

export const rsRenderInput = z.object(rsRenderInputShape);

export const rsRenderTool = defineTool({
  name: "rs_render",
  group: "redshift",
  title: "Render Redshift Outputs",
  description:
    "Run a guarded synchronous Redshift Beauty+AOV render. The client timeout does not cancel Cinema 4D rendering.",
  inputShape: rsRenderInputShape,
  async handler(args, client) {
    return textResult(await client.request("rs_render", rsRenderInput.parse(args), 1_800_000));
  },
});
