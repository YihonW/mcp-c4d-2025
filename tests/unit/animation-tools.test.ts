import { describe, expect, test } from "vitest";
import type { C4DClient } from "../../src/c4d-client.js";
import { setKeyframeTool } from "../../src/tools/set-keyframe.js";
import { getKeyframesTool } from "../../src/tools/get-keyframes.js";
import { deleteKeyframeTool } from "../../src/tools/delete-keyframe.js";
import { deleteTrackTool } from "../../src/tools/delete-track.js";
import { listTracksTool } from "../../src/tools/list-tracks.js";

const handle = { kind: "object", name: "Controller" };
const path = [
  [700, 5, 0],
  [1, 19, 0],
];
const trackTools = [setKeyframeTool, getKeyframesTool, deleteKeyframeTool, deleteTrackTool];

class FakeClient {
  requests: Array<{ command: string; params: unknown; timeout: number }> = [];
  async request(command: string, params: unknown, timeout: number) {
    this.requests.push({ command, params, timeout });
    return { ok: true };
  }
}

describe("animation track paths", () => {
  test.each(trackTools)("$name forwards complete paths and legacy selectors", async (tool) => {
    for (const selector of [{ path }, { param_id: 903, component: "x" }]) {
      const client = new FakeClient();
      const args = {
        handle,
        ...selector,
        ...(tool === setKeyframeTool ? { frame: 12, value: 1.5 } : {}),
      };
      await tool.handler(args as never, client as unknown as C4DClient);
      expect(client.requests).toEqual([
        { command: tool.name, params: args, timeout: tool === setKeyframeTool ? 15_000 : 10_000 },
      ]);
    }
  });

  test.each(trackTools)(
    "$name rejects missing, ambiguous, and malformed selectors without sending",
    async (tool) => {
      for (const selector of [
        {},
        { path, param_id: 700 },
        { path, component: "x" },
        { path: [] },
        { path: [[700, 5]] },
        { path: [700, 1] },
        { path: [[700, 5, true]] },
        { path: [[1, 19, Infinity]] },
        { path: Array.from({ length: 4 }, () => [1, 19, 0]) },
        { param_id: true },
        { param_id: 1.5 },
      ]) {
        const client = new FakeClient();
        const args = {
          handle,
          ...selector,
          ...(tool === setKeyframeTool ? { frame: 0, value: 1 } : {}),
        };
        await expect(tool.handler(args as never, client as unknown as C4DClient)).rejects.toThrow();
        expect(client.requests).toEqual([]);
      }
    },
  );

  test("set rejects non-finite values, invalid time, and conflicting dtype", async () => {
    for (const change of [
      { value: Infinity },
      { value: NaN },
      { frame: 0.5 },
      { frame: true },
      { frame: 2_147_483_648 },
      { fps: 0 },
      { fps: Infinity },
      { dtype: "long" },
    ]) {
      const client = new FakeClient();
      await expect(
        setKeyframeTool.handler(
          { handle, path, frame: 0, value: 1, ...change } as never,
          client as unknown as C4DClient,
        ),
      ).rejects.toThrow();
      expect(client.requests).toEqual([]);
    }
  });

  test.each([getKeyframesTool, deleteKeyframeTool])(
    "$name rejects reversed ranges",
    async (tool) => {
      const client = new FakeClient();
      await expect(
        tool.handler(
          { handle, path, start_frame: 2, end_frame: 1 } as never,
          client as unknown as C4DClient,
        ),
      ).rejects.toThrow();
      expect(client.requests).toEqual([]);
    },
  );

  test("delete rejects a single frame combined with range bounds", async () => {
    const client = new FakeClient();
    await expect(
      deleteKeyframeTool.handler(
        { handle, path, frame: 0, end_frame: 5 } as never,
        client as unknown as C4DClient,
      ),
    ).rejects.toThrow();
    expect(client.requests).toEqual([]);
  });

  test("list remains a read-only request", async () => {
    const client = new FakeClient();
    await listTracksTool.handler({ handle }, client as unknown as C4DClient);
    expect(client.requests).toEqual([
      { command: "list_tracks", params: { handle }, timeout: 10_000 },
    ]);
  });
});
