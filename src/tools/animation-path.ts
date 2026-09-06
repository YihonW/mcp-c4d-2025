import { z } from "zod";

export const animationInteger = z.number().int().min(-2_147_483_648).max(2_147_483_647);

export const animationSelectorShape = {
  param_id: animationInteger
    .optional()
    .describe("Legacy top-level parameter id; exclusive with path."),
  component: z
    .enum(["x", "y", "z"])
    .nullable()
    .optional()
    .describe("Legacy vector component with param_id; HPB rotation maps to x/y/z. Omit with path."),
  path: z
    .array(z.tuple([animationInteger, animationInteger, animationInteger]))
    .min(1)
    .max(3)
    .optional()
    .describe(
      "Full DescID as [[id,dtype,creator],...], from list_user_data desc_id or list_tracks path. For a vector append a REAL x/y/z DescLevel. Exclusive with param_id/component/dtype.",
    ),
};

export function validateAnimationSelector(
  value: { param_id?: number; component?: string | null; path?: number[][]; dtype?: string },
  ctx: z.RefinementCtx,
) {
  if ((value.path === undefined) === (value.param_id === undefined)) {
    ctx.addIssue({
      code: "custom",
      path: ["path"],
      message: "Provide exactly one of path or param_id",
    });
  }
  if (value.path !== undefined && (value.component != null || value.dtype !== undefined)) {
    ctx.addIssue({
      code: "custom",
      path: ["path"],
      message: "path cannot be combined with component or dtype",
    });
  }
}

export function validateAnimationRange(
  value: { start_frame?: number; end_frame?: number },
  ctx: z.RefinementCtx,
) {
  if (
    value.start_frame !== undefined &&
    value.end_frame !== undefined &&
    value.start_frame > value.end_frame
  ) {
    ctx.addIssue({
      code: "custom",
      path: ["end_frame"],
      message: "end_frame must be >= start_frame",
    });
  }
}
