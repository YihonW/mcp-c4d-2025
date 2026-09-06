import { describe, expect, test, vi } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { rsRenderInput, rsRenderTool } from "../../src/tools/rs-render.js";

const base = {
  document_name: "scene",
  render_data_name: "Final",
  output_path: "D:/renders/frame_0012.png",
  force: true as const,
};

describe("rs_render explicit frames", () => {
  test("preserves legacy input and accepts signed integer frames", () => {
    expect(rsRenderInput.parse(base)).toEqual(base);
    expect(rsRenderInput.parse({ ...base, frame: 0 }).frame).toBe(0);
    expect(rsRenderInput.parse({ ...base, frame: -3 }).frame).toBe(-3);
    for (const frame of [true, 1.5, "2", null, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(rsRenderInput.safeParse({ ...base, frame }).success).toBe(false);
    }
  });

  test("requires a frame when sequence safety is requested", () => {
    expect(rsRenderInput.safeParse({ ...base, sequence_frame: true }).success).toBe(false);
    expect(rsRenderInput.safeParse({ ...base, sequence_frame: false }).success).toBe(true);
    expect(rsRenderInput.safeParse({ ...base, sequence_frame: true, frame: 0 }).success).toBe(true);
  });

  test("forwards sequence safety and frame without changing the render timeout", async () => {
    const request = vi.fn().mockResolvedValue({ frame: 12 });
    const args = { ...base, frame: 12, sequence_frame: true };
    const result = await rsRenderTool.handler(args, { request } as unknown as C4DClient);
    expect(request).toHaveBeenCalledExactlyOnceWith("rs_render", args, 1_800_000);
    expect(JSON.parse(result.content[0].text)).toEqual({ frame: 12 });
  });

  test("rejects incomplete sequence input before contacting Cinema 4D", async () => {
    const request = vi.fn();
    await expect(
      rsRenderTool.handler({ ...base, sequence_frame: true }, { request } as unknown as C4DClient),
    ).rejects.toThrow(/requires frame/);
    expect(request).not.toHaveBeenCalled();
  });
});
