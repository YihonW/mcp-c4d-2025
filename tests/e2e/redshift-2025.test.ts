import { randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, describe, expect, test } from "vitest";

import {
  closeDocumentIfPresent,
  MCPTestClient,
  printSkipBanner,
  probeBridge,
  requireLiveBridge,
  requireRedshiftCapabilities,
} from "./harness.js";

const SUITE = "redshift-2025";
const strictLive = process.env.C4D_MCP_REQUIRE_LIVE === "1";
const probe = await probeBridge(SUITE);
let client: MCPTestClient | null = probe.client ?? null;
let ready = false;

if (probe.ready) {
  try {
    const baseCapabilities = await client!.call<{
      c4d_version: number;
      display_version: string;
      compatibility: string;
      platform: string;
      bridge_version: string;
      security: { loopback: boolean; token_required: boolean; exec_python: boolean };
    }>("get_capabilities");
    requireLiveBridge(probe, baseCapabilities, { tokenRequired: true, execPython: false });
    const redshiftCapabilities = await client!.call<unknown>("rs_get_capabilities");
    requireRedshiftCapabilities(redshiftCapabilities);
    ready = true;
  } catch (error) {
    await client!.close();
    client = null;
    if (strictLive) throw error;
    const reason = error instanceof Error ? error.message : String(error);
    printSkipBanner(SUITE, reason, "Cinema 4D 2025.3.2 Redshift capability gate failed");
  }
}

const workDir = ready ? mkdtempSync(path.join(tmpdir(), "c4d-mcp-redshift-2025-")) : "";
const documentName = `e2e_redshift_2025_${randomUUID().slice(0, 8)}`;
const suffix = randomUUID().slice(0, 8);
const sphereName = `e2e_rs_sphere_${suffix}`;
const floorName = `e2e_rs_floor_${suffix}`;
const materialName = `e2e_rs_material_${suffix}`;
const areaName = `e2e_rs_area_${suffix}`;
const domeName = `e2e_rs_dome_${suffix}`;
const cameraName = `e2e_rs_camera_${suffix}`;
const renderDataName = `e2e_rs_render_${suffix}`;
const aovName = `e2e_rs_aov_${suffix}`;
let creationAttempted = false;

type DocumentEntry = { index: number; name: string; path: string; active: boolean };
type DocumentList = { documents: DocumentEntry[]; count: number };
type BatchResult = { results: Array<{ result?: unknown; error?: string }>; count: number };

const withoutTransientIndex = ({ index: _index, ...document }: DocumentEntry) => document;

async function documentScopedGraphSnapshot(c: MCPTestClient): Promise<unknown> {
  const batch = await c.call<BatchResult>("batch", {
    document_name: documentName,
    undo_group: false,
    stop_on_error: true,
    ops: [
      {
        op: "list_graph_nodes",
        args: {
          handle: { kind: "material", name: materialName },
          node_space: "redshift",
        },
      },
    ],
  });
  expect(batch.results[0].error).toBeUndefined();
  return batch.results[0].result;
}

describe.skipIf(!ready)("Cinema 4D 2025.3.2 Redshift production path", () => {
  const c = client!;

  afterAll(async () => {
    try {
      if (creationAttempted) await closeDocumentIfPresent(c, documentName);
    } finally {
      await c.close();
      if (workDir) rmSync(workDir, { recursive: true, force: true });
    }
  });

  test(
    "renders one isolated 64x64 Beauty+AOV scene and restores the user session",
    { timeout: 1_920_000 },
    async () => {
      const texturePath = path.join(workDir, "one-pixel.png");
      const beautyPath = path.join(workDir, "beauty.png");
      const aovPath = path.join(workDir, "aov.png");
      const missingTexturePath = path.join(workDir, "missing-texture.png");
      writeFileSync(
        texturePath,
        Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=",
          "base64",
        ),
      );

      const originalDocuments = await c.call<DocumentList>("list_documents");
      const originalActive = originalDocuments.documents.filter((document) => document.active);
      expect(originalActive).toHaveLength(1);
      const originalActiveDocument = originalActive[0];

      creationAttempted = true;
      try {
        const created = await c.call<{ switched: boolean }>("new_document", {
          name: documentName,
          make_active: false,
        });
        expect(created.switched).toBe(false);

        const afterCreate = await c.call<DocumentList>("list_documents");
        expect(afterCreate.count).toBe(originalDocuments.count + 1);
        expect(
          afterCreate.documents.filter((document) => document.active).map(withoutTransientIndex),
        ).toEqual([withoutTransientIndex(originalActiveDocument)]);

        const createdObjects = await c.call<BatchResult>("batch", {
          document_name: documentName,
          undo_group: false,
          stop_on_error: true,
          ops: [
            {
              op: "create_entity",
              args: {
                kind: "object",
                type_id: "sphere",
                name: sphereName,
                position: [0, 50, 0],
              },
            },
            {
              op: "create_entity",
              args: { kind: "object", type_id: "plane", name: floorName },
            },
          ],
        });
        expect(createdObjects.results.map((entry) => entry.error)).toEqual([undefined, undefined]);

        await c.call("rs_create_material", { document_name: documentName, name: materialName });
        await c.call("rs_set_material_pbr", {
          document_name: documentName,
          material: { kind: "material", name: materialName },
          base_color: { path: texturePath },
          metalness: 0.15,
          roughness: 0.35,
        });
        await c.call("rs_create_light", {
          document_name: documentName,
          name: areaName,
          type: "area",
          position: [0, 150, -100],
          intensity: 100,
        });
        await c.call("rs_create_light", {
          document_name: documentName,
          name: domeName,
          type: "dome",
          dome_texture: texturePath,
          intensity: 0.5,
        });
        await c.call("rs_set_camera", {
          document_name: documentName,
          name: cameraName,
          position: [0, 100, -300],
        });

        const assigned = await c.call<BatchResult>("batch", {
          document_name: documentName,
          undo_group: false,
          stop_on_error: true,
          ops: [
            {
              op: "assign_material",
              args: {
                object: { kind: "object", name: sphereName },
                material: { kind: "material", name: materialName },
                projection: "spherical",
              },
            },
          ],
        });
        expect(assigned.results[0].error).toBeUndefined();

        const graphBefore = await documentScopedGraphSnapshot(c);
        const validationError = await c.callExpectError("rs_set_material_pbr", {
          document_name: documentName,
          material: { kind: "material", name: materialName },
          base_color: { path: missingTexturePath },
        });
        expect(validationError).toMatch(/file not found/i);
        expect(await documentScopedGraphSnapshot(c)).toEqual(graphBefore);
        const afterRejectedWrite = await c.call<DocumentList>("list_documents");
        expect(
          afterRejectedWrite.documents
            .filter((document) => document.active)
            .map(withoutTransientIndex),
        ).toEqual([withoutTransientIndex(originalActiveDocument)]);

        const redshiftCapabilities = await c.call<{
          aov_api: { aliases: Record<string, number> };
        }>("rs_get_capabilities");
        const preferredAlias = ["depth", "normal", "reflection", "diffuse_lighting", "beauty"].find(
          (alias) => redshiftCapabilities.aov_api.aliases[alias] !== undefined,
        );
        expect(preferredAlias).toBeDefined();

        await c.call("rs_configure_render", {
          document_name: documentName,
          name: renderDataName,
          width: 64,
          height: 64,
          frame: 0,
          output_format: "png",
          beauty_path: beautyPath,
          make_active: false,
        });
        await c.call("rs_upsert_aov", {
          document_name: documentName,
          render_data_name: renderDataName,
          type: preferredAlias,
          name: aovName,
          enabled: true,
          multipass_enabled: true,
          direct_file_enabled: true,
          direct_file_path: aovPath,
        });

        const rendered = await c.call<{
          renderer: { id: number; name: string };
          width: number;
          height: number;
          beauty: { path: string; size: number };
          aovs: Array<{ path: string; size: number }>;
          expected_missing: unknown[];
          duration_ms: number;
        }>(
          "rs_render",
          {
            document_name: documentName,
            render_data_name: renderDataName,
            output_path: beautyPath,
            force: true,
            overwrite: false,
          },
          { timeoutMs: 1_800_000 },
        );
        expect(rendered.renderer).toEqual({ id: 1036219, name: "Redshift" });
        expect(rendered).toMatchObject({ width: 64, height: 64 });
        expect(rendered.beauty).toEqual({ path: beautyPath, size: expect.any(Number) });
        expect(rendered.beauty.size).toBeGreaterThan(0);
        expect(rendered.aovs.length).toBeGreaterThan(0);
        expect(rendered.aovs.every((item) => item.size > 0 && existsSync(item.path))).toBe(true);
        expect(rendered.expected_missing).toEqual([]);
        expect(rendered.duration_ms).toBeGreaterThanOrEqual(0);

        const listedAovs = await c.call<{ render_data: { name: string } }>("rs_list_aovs", {
          document_name: documentName,
          render_data_name: renderDataName,
        });
        expect(listedAovs.render_data.name).toBe(renderDataName);

        await closeDocumentIfPresent(c, documentName);
        creationAttempted = false;
        expect(await c.call<DocumentList>("list_documents")).toEqual(originalDocuments);
      } finally {
        if (creationAttempted) {
          await closeDocumentIfPresent(c, documentName);
          creationAttempted = false;
          expect(await c.call<DocumentList>("list_documents")).toEqual(originalDocuments);
        }
      }
    },
  );
});
