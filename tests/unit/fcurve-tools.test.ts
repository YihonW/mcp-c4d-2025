import { describe, expect, test } from "vitest";
import type { C4DClient } from "../../src/c4d-client.js";
import {
  editFcurveKeysTool,
  getFcurveTool,
  setTrackExtrapolationTool,
  transformFcurveTool,
} from "../../src/tools/fcurves.js";
import { ALL_TOOLS } from "../../src/tools/index.js";

const common = {
  document_name: "曲线测试.c4d",
  handle: { kind: "object", name: "Controller" },
  path: [
    [700, 5, 0],
    [1, 19, 0],
  ],
};
const fixtures = [
  { tool: getFcurveTool, extra: { sample_frames: [-0.25, 0, 12.5] }, timeout: 10_000 },
  { tool: editFcurveKeysTool, extra: { edits: [{ key_index: 0, value: 3 }] }, timeout: 15_000 },
  { tool: transformFcurveTool, extra: { time_offset_frames: 0.5 }, timeout: 15_000 },
  { tool: setTrackExtrapolationTool, extra: { after: "oscillate" }, timeout: 15_000 },
];

class FakeClient {
  requests: Array<{ command: string; params: unknown; timeout: number }> = [];
  async request(command: string, params: unknown, timeout: number) {
    this.requests.push({ command, params, timeout });
    return { ok: true };
  }
}

describe("F-Curve tools", () => {
  test.each(fixtures)(
    "$tool.name is registered and forwards both selectors",
    async ({ tool, extra, timeout }) => {
      expect(ALL_TOOLS.filter((entry) => entry.name === tool.name)).toEqual([tool]);
      for (const selector of [{ path: common.path }, { param_id: 903, component: "x" }]) {
        const client = new FakeClient();
        const args = {
          document_name: common.document_name,
          handle: common.handle,
          ...selector,
          ...extra,
          fps: 24,
        };
        await tool.handler(args as never, client as unknown as C4DClient);
        expect(client.requests).toEqual([{ command: tool.name, params: args, timeout }]);
      }
    },
  );

  test.each(fixtures)(
    "$tool.name rejects bad common fields before transport",
    async ({ tool, extra }) => {
      for (const change of [
        { document_name: undefined },
        { document_name: "" },
        { document_name: "  " },
        { path: undefined },
        { path: [] },
        { path: common.path, param_id: 700 },
        { path: common.path, component: "x" },
        { path: [[700, 5, false]] },
        { fps: 0 },
        { fps: true },
        { fps: 1.5 },
        { fps: Infinity },
        { unexpected: true },
      ]) {
        const client = new FakeClient();
        await expect(
          tool.handler({ ...common, ...extra, ...change } as never, client as unknown as C4DClient),
        ).rejects.toThrow();
        expect(client.requests).toEqual([]);
      }
    },
  );

  test("sample bounds reject oversized, non-finite or nonnumeric requests", async () => {
    for (const sample_frames of [
      [],
      Array(301).fill(1),
      [1_000_001],
      [NaN],
      [Infinity],
      [true],
      ["1"],
    ]) {
      const client = new FakeClient();
      await expect(
        getFcurveTool.handler(
          { ...common, sample_frames } as never,
          client as unknown as C4DClient,
        ),
      ).rejects.toThrow();
      expect(client.requests).toEqual([]);
    }
  });

  test("manual tangent offsets and zero values are retained verbatim", async () => {
    const client = new FakeClient();
    const args = {
      ...common,
      edits: [
        {
          key_index: 0,
          value: 0,
          interp: "spline",
          tangent_mode: "manual",
          left: { dt_frames: -2.5, dv: -1 },
          right: { dt_frames: 3.5, dv: 2 },
        },
      ],
    };
    await editFcurveKeysTool.handler(args as never, client as unknown as C4DClient);
    expect(client.requests[0].params).toEqual(args);
  });

  test("edits reject empty, duplicate, misspelled and incompatible operations", async () => {
    for (const edits of [
      [],
      [{ key_index: 0 }],
      Array(1001).fill({ key_index: 0, value: 1 }),
      [
        { key_index: 0, value: 1 },
        { key_index: 0, interp: "linear" },
      ],
      [{ key_index: -1, value: 1 }],
      [{ key_index: 1000, value: 1 }],
      [{ key_index: 0.5, value: 1 }],
      [{ key_index: 0, value: Infinity }],
      [{ key_index: 0, value: true }],
      [{ key_index: 0, interpolation: "linear" }],
      [{ key_index: 0, tangent_mode: "auto", left: { dt_frames: -1, dv: 0 } }],
      [{ key_index: 0, left: { dt_frames: -1, dv: 0 } }],
      [{ key_index: 0, tangent_mode: "manual", left: { dt_frames: 0, dv: 0 } }],
      [{ key_index: 0, tangent_mode: "manual", right: { dt_frames: -1, dv: 0 } }],
      [{ key_index: 0, tangent_mode: "manual", right: { dt_frames: 1, dv: NaN } }],
      [{ key_index: 0, tangent_mode: "manual", right: { dt_frames: 1, dv: 0, typo: 1 } }],
    ]) {
      const client = new FakeClient();
      await expect(
        editFcurveKeysTool.handler({ ...common, edits } as never, client as unknown as C4DClient),
      ).rejects.toThrow();
      expect(client.requests).toEqual([]);
    }
  });

  test("transform accepts subframes, zero/negative value scales and explicit identity", async () => {
    for (const values of [
      { time_scale: 1 },
      {
        key_indices: [2, 0],
        time_scale: 0.5,
        time_offset_frames: -2.25,
        pivot_frame: 12.5,
        value_scale: -1,
        value_pivot: 3,
      },
      { value_scale: 0, value_offset: 0 },
    ]) {
      const client = new FakeClient();
      const args = { ...common, ...values };
      await transformFcurveTool.handler(args as never, client as unknown as C4DClient);
      expect(client.requests[0].params).toEqual(args);
    }
  });

  test("transform rejects no-op payloads, invalid indices and unsafe time scales", async () => {
    for (const values of [
      {},
      { key_indices: [0] },
      { time_scale: 0 },
      { time_scale: -1 },
      { time_scale: Infinity },
      { time_scale: 1_000_001 },
      { time_offset_frames: 1_000_001 },
      { pivot_frame: NaN },
      { value_scale: Infinity },
      { value_offset: true },
      { time_scale: 1, key_indices: [] },
      { time_scale: 1, key_indices: [0, 0] },
      { time_scale: 1, key_indices: [0.5] },
      { time_scale: 1, key_indices: Array(1001).fill(0) },
    ]) {
      const client = new FakeClient();
      await expect(
        transformFcurveTool.handler(
          { ...common, ...values } as never,
          client as unknown as C4DClient,
        ),
      ).rejects.toThrow();
      expect(client.requests).toEqual([]);
    }
  });

  test("all documented extrapolation modes pass without defaulting the other side", async () => {
    for (const mode of ["off", "constant", "linear", "repeat", "offset_repeat", "oscillate"]) {
      const client = new FakeClient();
      const args = { ...common, before: mode };
      await setTrackExtrapolationTool.handler(args as never, client as unknown as C4DClient);
      expect(client.requests[0].params).toEqual(args);
    }
  });

  test("extrapolation rejects missing or unknown modes before transport", async () => {
    for (const modes of [{}, { before: "bezier" }, { after: true }, { before: null }]) {
      const client = new FakeClient();
      await expect(
        setTrackExtrapolationTool.handler(
          { ...common, ...modes } as never,
          client as unknown as C4DClient,
        ),
      ).rejects.toThrow();
      expect(client.requests).toEqual([]);
    }
  });
});
