import { describe, expect, test } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { ALL_TOOLS } from "../../src/tools/index.js";
import { rsGetCapabilitiesTool } from "../../src/tools/rs-get-capabilities.js";

class FakeC4DClient {
  readonly requests: Array<{
    command: string;
    params: Record<string, unknown>;
    timeoutMs: number;
  }> = [];

  async request(command: string, params: Record<string, unknown>, timeoutMs: number) {
    this.requests.push({ command, params, timeoutMs });
    return { renderer: { supported: true } };
  }
}

describe("rs_get_capabilities", () => {
  test("is registered as a Redshift tool and requests the exact read-only capability command", async () => {
    const client = new FakeC4DClient();

    const result = await rsGetCapabilitiesTool.handler({}, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsGetCapabilitiesTool);
    expect(rsGetCapabilitiesTool.group).toBe("redshift");
    expect(client.requests).toEqual([
      { command: "rs_get_capabilities", params: {}, timeoutMs: 10_000 },
    ]);
    expect(JSON.parse(result.content[0].text)).toEqual({ renderer: { supported: true } });
  });
});
