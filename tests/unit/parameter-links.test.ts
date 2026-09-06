import { z } from "zod";
import { describe, expect, test, vi } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { setParamsTool } from "../../src/tools/set-params.js";

const input = z.object(setParamsTool.inputShape);
const handle = { kind: "object", path: "/Rig" };

describe("set_params object links", () => {
  test("accepts explicit links and clearing with full user-data DescID paths", () => {
    const args = {
      handle,
      values: [
        { path: 1000, value: { link: { kind: "object", path: "/Target" } } },
        {
          path: [
            [700, 5, 0],
            [1, 133, 100001],
          ],
          value: { link: null },
        },
      ],
    };

    expect(input.parse(args)).toEqual(args);
  });

  test("rejects malformed or implicit links without changing primitive value support", () => {
    for (const value of [
      null,
      {},
      { kind: "object", name: "Target" },
      { link: {} },
      { link: "Target" },
      { link: null, extra: true },
    ]) {
      expect(input.safeParse({ handle, values: [{ path: 1000, value }] }).success).toBe(false);
    }
    for (const value of [true, 0, 1.25, "name", [1, 2, 3], [1, 2]]) {
      expect(input.parse({ handle, values: [{ path: 1000, value }] }).values[0].value).toEqual(
        value,
      );
    }
  });

  test("forwards the link wrapper unchanged and preserves bridge validation errors", async () => {
    const args = {
      handle,
      values: [{ path: 1000, value: { link: { kind: "object", name: "Target" } } }],
    };
    const response = { applied: [], errors: [{ path: [1000], error: "link handle not resolved" }] };
    const client = { request: vi.fn().mockResolvedValue(response) };

    const result = await setParamsTool.handler(args, client as unknown as C4DClient);

    expect(client.request).toHaveBeenCalledWith("set_params", args, 15_000);
    expect(JSON.parse(result.content[0].text)).toEqual(response);
  });
});
