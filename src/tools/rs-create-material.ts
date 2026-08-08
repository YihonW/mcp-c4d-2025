import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

export const rsCreateMaterialTool = defineTool({
  name: "rs_create_material",
  group: "redshift",
  title: "Create Redshift Material",
  description: "Create a Redshift node material, or reuse one exact-name match when requested.",
  inputShape: {
    document_name: z
      .string()
      .optional()
      .describe("Open document name; defaults to the active document."),
    name: z.string().trim().min(1).describe("Material name."),
    update_if_exists: z
      .boolean()
      .optional()
      .describe("Reuse an existing material only when its name is unique."),
  },
  async handler(args, client) {
    return textResult(await client.request("rs_create_material", args, 30_000));
  },
});
