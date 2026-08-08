import { z } from "zod";
import { describe, expect, test } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { ALL_TOOLS } from "../../src/tools/index.js";
import { rsCreateMaterialTool } from "../../src/tools/rs-create-material.js";
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

describe("rs_create_material", () => {
  test("requires a non-empty trimmed name and accepts optional document and update fields", () => {
    const input = z.object(rsCreateMaterialTool.inputShape);

    expect(input.safeParse({ name: "   " }).success).toBe(false);
    expect(input.parse({ name: "  RS_Mat  " })).toEqual({ name: "RS_Mat" });
    expect(input.parse({ document_name: "scene", name: "RS_Mat", update_if_exists: true })).toEqual(
      { document_name: "scene", name: "RS_Mat", update_if_exists: true },
    );
  });

  test("is registered and forwards the exact material request with a 30-second timeout", async () => {
    const client = new FakeC4DClient();
    const args = { document_name: "scene", name: "RS_Mat", update_if_exists: true };

    await rsCreateMaterialTool.handler(args, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsCreateMaterialTool);
    expect(rsCreateMaterialTool.group).toBe("redshift");
    expect(client.requests).toEqual([
      { command: "rs_create_material", params: args, timeoutMs: 30_000 },
    ]);
  });
});
