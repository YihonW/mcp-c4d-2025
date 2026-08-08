import { describe, expect, test } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { batchTool } from "../../src/tools/batch.js";

class FakeC4DClient {
  requests: Array<{ command: string; params: Record<string, unknown>; timeoutMs: number }> = [];

  async request(
    command: string,
    params: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<{ results: unknown[] }> {
    this.requests.push({ command, params, timeoutMs });
    return { results: [] };
  }
}

describe("batch tool document scope", () => {
  test("accepts and forwards document_name with undo_group=false", async () => {
    expect(batchTool.inputShape.document_name.parse("e2e-temp")).toBe("e2e-temp");
    expect(batchTool.inputShape.undo_group.parse(false)).toBe(false);
    const client = new FakeC4DClient();
    const args = {
      document_name: "e2e-temp",
      undo_group: false,
      ops: [{ op: "get_document_state" }],
      stop_on_error: true,
    };

    await batchTool.handler(args, client as unknown as C4DClient);

    expect(client.requests).toEqual([{ command: "batch", params: args, timeoutMs: 33_000 }]);
  });
});
