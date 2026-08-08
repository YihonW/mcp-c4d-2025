import { describe, expect, test } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { getCapabilitiesTool } from "../../src/tools/get-capabilities.js";

const bridgePayload = {
  c4d_version: 2025302,
  python_version: "3.11.9",
  platform: "win32",
  bridge_version: "0.4.0",
  security: { loopback: true, token_required: true, exec_python: false },
  groups: ["basics", "entities", "transform"],
  features: { node_materials: true, scene_nodes: true },
  plugins: [],
};

class FakeC4DClient {
  readonly requests: Array<{
    command: string;
    params: Record<string, unknown>;
    timeoutMs: number;
  }> = [];

  async request(
    command: string,
    params: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<typeof bridgePayload> {
    this.requests.push({ command, params, timeoutMs });
    return bridgePayload;
  }
}

describe("get_capabilities", () => {
  test("enriches the bridge payload with the supported Cinema 4D release", async () => {
    const client = new FakeC4DClient();

    const result = await getCapabilitiesTool.handler({}, client as unknown as C4DClient);

    expect(client.requests).toEqual([
      { command: "get_capabilities", params: {}, timeoutMs: 5_000 },
    ]);
    expect(JSON.parse(result.content[0].text)).toEqual({
      ...bridgePayload,
      display_version: "2025.3.2",
      compatibility: "supported",
    });
  });
});
