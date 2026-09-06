import { z } from "zod";
import { defineTool, textResult } from "./define-tool.js";
import { handleDescription, handleSchema } from "./handle.js";

// Each path segment is one of:
//   - an int id (common case)
//   - "x" | "y" | "z" (vector sub-component)
//   - [id, "real"|"long"|"bool"|"vector"] (explicit dtype alias)
//   - [id, dtype_int, creator_int] (bridge-internal DescLevel echo, emitted
//     by list_user_data so callers can pipe that shape straight back)
const pathSegment = z.union([
  z.number().int(),
  z.enum(["x", "y", "z"]),
  z.tuple([z.union([z.number().int(), z.enum(["x", "y", "z"])]), z.string()]),
  z.array(z.number().int()).min(2).max(3),
]);

const pathSchema = z.union([z.number().int(), z.array(pathSegment).min(1)]);

export const setParamsTool = defineTool({
  name: "set_params",
  group: "crud",
  title: "Set Parameter Values",
  description:
    "Write parameter values in one undo group. Each entry is `{path, value}` where `path` is either an int id or a DescID path (e.g. [903, 'x'] = position.x). Lists of 3 numbers auto-coerce into c4d.Vector for vector-typed destinations. For DTYPE_BASELISTLINK parameters only, use `{link: <handle>}` to reference an entity or `{link: null}` to clear it. Link targets and destination types are validated before any writes. Returns `{applied: [{path, value}], errors: [{path, error}]}`; inspect errors for rejected writes.",
  inputShape: {
    handle: handleSchema.describe(handleDescription),
    values: z
      .array(
        z.object({
          path: pathSchema,
          value: z.union([
            z.boolean(),
            z.number(),
            z.string(),
            z.array(z.number()),
            z.strictObject({ link: handleSchema.nullable() }),
          ]),
        }),
      )
      .describe("Writes to apply. Wrapped in an undo group."),
  },
  async handler(args, client) {
    return textResult(
      await client.request("set_params", { handle: args.handle, values: args.values }, 15_000),
    );
  },
});
