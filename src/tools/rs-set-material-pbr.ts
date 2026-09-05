import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

const unitInterval = z.number().min(0).max(1);
const textureInput = z.object({
  path: z.string().trim().min(1).describe("Absolute texture file path."),
  color_space: z.string().trim().min(1).optional().describe("Exact OCIO color-space name."),
});
const materialHandle = z.object({
  kind: z.literal("material"),
  name: z.string().trim().min(1),
});

export const rsSetMaterialPbrInputShape = {
  document_name: z.string().trim().min(1).optional().describe("Open document name."),
  material: materialHandle.describe("Target Redshift material handle."),
  base_color: z
    .union([z.tuple([unitInterval, unitInterval, unitInterval]), textureInput])
    .optional(),
  metalness: z.union([unitInterval, textureInput]).optional(),
  roughness: z.union([unitInterval, textureInput]).optional(),
  normal: z.object({ texture: textureInput, strength: unitInterval.optional() }).optional(),
  displacement: z
    .object({ texture: textureInput, scale: z.number().finite().optional() })
    .optional(),
  replace_graph: z.boolean().optional(),
};

export const rsSetMaterialPbrInput = z
  .object(rsSetMaterialPbrInputShape)
  .superRefine((value, ctx) => {
    if (value.replace_graph === true && value.document_name === undefined) {
      ctx.addIssue({
        code: "custom",
        path: ["document_name"],
        message: "document_name is required when replace_graph is true",
      });
    }
  });

export const rsSetMaterialPbrTool = defineTool({
  name: "rs_set_material_pbr",
  group: "redshift",
  title: "Set Redshift PBR Material",
  description:
    "Patch supplied Redshift Standard Material PBR channels. Texture paths are prevalidated; replace_graph requires an explicit document and reliable rollback support.",
  inputShape: rsSetMaterialPbrInputShape,
  async handler(args, client) {
    const parsed = rsSetMaterialPbrInput.parse(args);
    return textResult(await client.request("rs_set_material_pbr", parsed, 30_000));
  },
});
