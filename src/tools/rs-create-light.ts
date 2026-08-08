import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

const finiteNumber = z.number().finite();
const positiveNumber = finiteNumber.positive();
const rgb = z.tuple([
  finiteNumber.min(0).max(1),
  finiteNumber.min(0).max(1),
  finiteNumber.min(0).max(1),
]);
const transform = z.tuple([finiteNumber, finiteNumber, finiteNumber]);

export const rsCreateLightTool = defineTool({
  name: "rs_create_light",
  group: "redshift",
  title: "Create Redshift Light",
  description: "Create or update a native Redshift light using only runtime-supported properties.",
  inputShape: {
    document_name: z.string().trim().min(1).optional().describe("Open document name."),
    name: z.string().trim().min(1).describe("Light name."),
    type: z.enum(["area", "dome", "sun", "point", "spot"]),
    update_if_exists: z.boolean().optional(),
    position: transform.optional(),
    rotation: transform.optional(),
    color: rgb.optional(),
    intensity: positiveNumber.optional(),
    exposure: finiteNumber.optional(),
    dome_texture: z.string().trim().min(1).optional().describe("Absolute dome texture path."),
  },
  async handler(args, client) {
    return textResult(await client.request("rs_create_light", args, 30_000));
  },
});
