import { z } from "zod";

import { defineTool, textResult } from "./define-tool.js";

const finiteNumber = z.number().finite();
const positiveNumber = finiteNumber.positive();
const transform = z.tuple([finiteNumber, finiteNumber, finiteNumber]);

export const rsSetCameraTool = defineTool({
  name: "rs_set_camera",
  group: "redshift",
  title: "Set Redshift Camera",
  description:
    "Create or update a native Redshift camera and report unavailable requested settings.",
  inputShape: {
    document_name: z.string().trim().min(1).optional().describe("Open document name."),
    name: z.string().trim().min(1).describe("Camera name."),
    update_if_exists: z.boolean().optional(),
    position: transform.optional(),
    rotation: transform.optional(),
    exposure: finiteNumber.optional(),
    shutter_time: positiveNumber.optional(),
    shutter_angle: finiteNumber.optional(),
    focus_distance: positiveNumber.optional(),
    f_stop: positiveNumber.optional(),
    depth_of_field: z.boolean().optional(),
  },
  async handler(args, client) {
    return textResult(await client.request("rs_set_camera", args, 30_000));
  },
});
