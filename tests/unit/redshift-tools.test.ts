import { z } from "zod";
import { describe, expect, test } from "vitest";

import type { C4DClient } from "../../src/c4d-client.js";
import { ALL_TOOLS } from "../../src/tools/index.js";
import { rsCreateMaterialTool } from "../../src/tools/rs-create-material.js";
import { rsCreateLightTool } from "../../src/tools/rs-create-light.js";
import { rsGetCapabilitiesTool } from "../../src/tools/rs-get-capabilities.js";
import { rsSetCameraTool } from "../../src/tools/rs-set-camera.js";
import { rsListAovsTool } from "../../src/tools/rs-list-aovs.js";
import {
  rsSetMaterialPbrInput,
  rsSetMaterialPbrTool,
} from "../../src/tools/rs-set-material-pbr.js";
import { rsUpsertAovInput, rsUpsertAovTool } from "../../src/tools/rs-upsert-aov.js";

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

describe("rs_create_light", () => {
  test("validates exact light input ranges and fixed transform tuples", () => {
    const input = z.object(rsCreateLightTool.inputShape);

    expect(input.safeParse({ name: "RS_Area", type: "area", color: [0, 0.5, 1] }).success).toBe(
      true,
    );
    expect(input.safeParse({ name: "RS_Area", type: "area", color: [0, 0.5, 1.01] }).success).toBe(
      false,
    );
    expect(input.safeParse({ name: "RS_Area", type: "area", intensity: 0 }).success).toBe(false);
    expect(input.safeParse({ name: "RS_Area", type: "area", position: [1, 2] }).success).toBe(
      false,
    );
    expect(
      input.safeParse({ name: "RS_Area", type: "area", rotation: [0, 1, Number.NaN] }).success,
    ).toBe(false);
  });

  test("is registered and forwards the exact light request with a 30-second timeout", async () => {
    const client = new FakeC4DClient();
    const args = {
      document_name: "scene",
      name: "RS_Dome",
      type: "dome" as const,
      dome_texture: "C:/textures/dome.exr",
    };

    await rsCreateLightTool.handler(args, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsCreateLightTool);
    expect(rsCreateLightTool.group).toBe("redshift");
    expect(client.requests).toEqual([
      { command: "rs_create_light", params: args, timeoutMs: 30_000 },
    ]);
  });
});

describe("rs_set_camera", () => {
  test("validates positive camera parameters, finite transforms, and optional update fields", () => {
    const input = z.object(rsSetCameraTool.inputShape);

    expect(input.safeParse({ name: "RS_Camera", exposure: -2, shutter_time: 0.25 }).success).toBe(
      true,
    );
    expect(input.safeParse({ name: "RS_Camera", shutter_time: 0 }).success).toBe(false);
    expect(input.safeParse({ name: "RS_Camera", focus_distance: -1 }).success).toBe(false);
    expect(input.safeParse({ name: "RS_Camera", f_stop: Number.POSITIVE_INFINITY }).success).toBe(
      false,
    );
    expect(input.safeParse({ name: "RS_Camera", position: [1, 2, Number.NaN] }).success).toBe(
      false,
    );
  });

  test("is registered and forwards the exact camera request with a 30-second timeout", async () => {
    const client = new FakeC4DClient();
    const args = { document_name: "scene", name: "RS_Camera", update_if_exists: true, f_stop: 2.8 };

    await rsSetCameraTool.handler(args, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsSetCameraTool);
    expect(rsSetCameraTool.group).toBe("redshift");
    expect(client.requests).toEqual([
      { command: "rs_set_camera", params: args, timeoutMs: 30_000 },
    ]);
  });
});

describe("rs_set_material_pbr", () => {
  test("validates PBR ranges, finite displacement scale, and destructive cross-field guard", () => {
    const material = { kind: "material", name: "RS_Mat" } as const;

    expect(rsSetMaterialPbrInput.safeParse({ material, base_color: [0, 0.5, 1] }).success).toBe(
      true,
    );
    expect(rsSetMaterialPbrInput.safeParse({ material, base_color: [0, 0.5, 1.01] }).success).toBe(
      false,
    );
    expect(rsSetMaterialPbrInput.safeParse({ material, metalness: -0.01 }).success).toBe(false);
    expect(rsSetMaterialPbrInput.safeParse({ material, roughness: 1.01 }).success).toBe(false);
    expect(
      rsSetMaterialPbrInput.safeParse({
        material,
        normal: { texture: { path: "C:/textures/normal.png" }, strength: 1.01 },
      }).success,
    ).toBe(false);
    expect(
      rsSetMaterialPbrInput.safeParse({
        material,
        displacement: {
          texture: { path: "C:/textures/displace.exr" },
          scale: Number.POSITIVE_INFINITY,
        },
      }).success,
    ).toBe(false);
    expect(
      rsSetMaterialPbrInput.safeParse({ material, replace_graph: true, roughness: 0.35 }).success,
    ).toBe(false);
    expect(
      rsSetMaterialPbrInput.parse({
        document_name: "scene",
        material,
        replace_graph: true,
        roughness: 0.35,
      }),
    ).toEqual({ document_name: "scene", material, replace_graph: true, roughness: 0.35 });
  });

  test("is registered and forwards the unchanged PBR request with a 30-second timeout", async () => {
    const client = new FakeC4DClient();
    const args = {
      document_name: "scene",
      material: { kind: "material" as const, name: "RS_Mat" },
      base_color: { path: "C:/textures/base.exr", color_space: "acescg" },
      roughness: 0.35,
    };

    await rsSetMaterialPbrTool.handler(args, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsSetMaterialPbrTool);
    expect(rsSetMaterialPbrTool.group).toBe("redshift");
    expect(client.requests).toEqual([
      { command: "rs_set_material_pbr", params: args, timeoutMs: 30_000 },
    ]);
  });

  test("rejects destructive replacement without a document before contacting the bridge", async () => {
    const client = new FakeC4DClient();

    await expect(
      rsSetMaterialPbrTool.handler(
        {
          material: { kind: "material", name: "RS_Mat" },
          replace_graph: true,
          roughness: 0.35,
        },
        client as unknown as C4DClient,
      ),
    ).rejects.toThrow(/document_name/);
    expect(client.requests).toEqual([]);
  });
});

describe("Redshift AOV tools", () => {
  test("list is registered and forwards its optional document and RenderData selection", async () => {
    const client = new FakeC4DClient();
    const args = { document_name: "scene", render_data_name: "Final" };

    await rsListAovsTool.handler(args, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsListAovsTool);
    expect(rsListAovsTool.group).toBe("redshift");
    expect(client.requests).toEqual([{ command: "rs_list_aovs", params: args, timeoutMs: 10_000 }]);
  });

  test("upsert accepts a trimmed alias or integer and guards an enabled direct output path", () => {
    const input = rsUpsertAovInput;

    expect(input.parse({ type: "  beauty  ", name: "  Beauty  " })).toEqual({
      type: "beauty",
      name: "Beauty",
    });
    expect(input.safeParse({ type: 44, name: "Custom" }).success).toBe(true);
    expect(input.safeParse({ type: 1.25, name: "Custom" }).success).toBe(false);
    expect(
      input.safeParse({ type: "beauty", name: "Beauty", direct_file_enabled: true }).success,
    ).toBe(false);
    expect(
      input.safeParse({
        type: "beauty",
        name: "Beauty",
        direct_file_enabled: true,
        direct_file_path: "C:/renders/beauty.exr",
      }).success,
    ).toBe(true);
  });

  test("upsert is registered and forwards an unmodified AOV request", async () => {
    const client = new FakeC4DClient();
    const args = { type: "beauty", name: "Beauty", params: { "9001": 1.5 } };

    await rsUpsertAovTool.handler(args, client as unknown as C4DClient);

    expect(ALL_TOOLS).toContain(rsUpsertAovTool);
    expect(rsUpsertAovTool.group).toBe("redshift");
    expect(client.requests).toEqual([
      { command: "rs_upsert_aov", params: args, timeoutMs: 30_000 },
    ]);
  });
});
