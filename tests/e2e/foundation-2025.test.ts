import { randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, describe, expect, test } from "vitest";

import { MCPTestClient, printSkipBanner, probeBridge, requireLiveBridge } from "./harness.js";

const SUITE = "foundation-2025";
const CUBE_NAME = "e2e_foundation_cube";
const TARGET_POSITION = [100, 20, -30];
const strictLive = process.env.C4D_MCP_REQUIRE_LIVE === "1";

const probe = await probeBridge(SUITE);
let client: MCPTestClient | null = probe.client ?? null;
let is2025 = false;

if (probe.ready) {
  try {
    const capabilities = await client!.call<{ c4d_version: number }>("get_capabilities");
    is2025 = Math.floor(capabilities.c4d_version / 1000) === 2025;
    if (strictLive) {
      requireLiveBridge(probe, capabilities);
    } else if (!is2025) {
      printSkipBanner(
        SUITE,
        `bridge reports Cinema 4D release ${Math.floor(capabilities.c4d_version / 1000)}`,
        "Cinema 4D 2025 required",
      );
      await client!.close();
      client = null;
    }
  } catch (err) {
    await client!.close();
    client = null;
    if (strictLive) throw err;
    const reason = err instanceof Error ? err.message : String(err);
    printSkipBanner(SUITE, reason, "Cinema 4D 2025 capability probe failed");
  }
}

const ready = probe.ready && is2025;
const workDir = ready ? mkdtempSync(path.join(tmpdir(), "c4d-mcp-foundation-2025-")) : "";
const documentName = `e2e_foundation_2025_${randomUUID().slice(0, 8)}`;
let temporaryDocumentOpen = false;

async function closeTemporaryDocument(): Promise<void> {
  if (!temporaryDocumentOpen) return;
  await client!.call("close_document", { name: documentName, force: true });
  temporaryDocumentOpen = false;
}

describe.skipIf(!ready)("Cinema 4D 2025 foundation", () => {
  const c = client!;

  afterAll(async () => {
    try {
      await closeTemporaryDocument();
    } finally {
      await c.close();
      if (workDir) rmSync(workDir, { recursive: true, force: true });
    }
  });

  test("creates, transforms, verifies, undoes, previews, and saves a temporary scene", async () => {
    const previewPath = path.join(workDir, "foundation-preview.png");
    const scenePath = path.join(workDir, "foundation-scene.c4d");

    await c.call("new_document", { name: documentName, make_active: true });
    temporaryDocumentOpen = true;

    try {
      await c.call("create_entity", { kind: "object", type_id: "cube", name: CUBE_NAME });
      const before = await c.call<{ samples: Array<{ pos: number[] }> }>("sample_transform", {
        handle: { kind: "object", name: CUBE_NAME },
        frames: [0],
        space: "local",
      });

      await c.call("set_transform", {
        handle: { kind: "object", name: CUBE_NAME },
        pos: TARGET_POSITION,
        space: "local",
      });
      const transformed = await c.call<{ samples: Array<{ pos: number[] }> }>("sample_transform", {
        handle: { kind: "object", name: CUBE_NAME },
        frames: [0],
        space: "local",
      });
      expect(transformed.samples[0].pos).toEqual(TARGET_POSITION);

      const undo = await c.call<{ steps_performed: number }>("undo", { steps: 1 });
      expect(undo.steps_performed).toBe(1);
      const reverted = await c.call<{ samples: Array<{ pos: number[] }> }>("sample_transform", {
        handle: { kind: "object", name: CUBE_NAME },
        frames: [0],
        space: "local",
      });
      expect(reverted.samples[0].pos).toEqual(before.samples[0].pos);

      const preview = await c.callRaw(
        "preview_render",
        { width: 64, height: 64, view: "front", save_path: previewPath },
        { timeoutMs: 60_000 },
      );
      expect(preview.content.some((part) => part.type === "image")).toBe(true);
      const previewText = preview.content.find((part) => part.type === "text") as
        | { text: string }
        | undefined;
      const previewMeta = JSON.parse(previewText?.text ?? "{}") as {
        width?: number;
        height?: number;
        saved_path?: string;
      };
      expect(previewMeta).toMatchObject({ width: 64, height: 64, saved_path: previewPath });
      expect(existsSync(previewPath)).toBe(true);

      const saved = await c.call<{ path: string; format: string }>("save_document", {
        path: scenePath,
        format: "c4d",
        copy: true,
      });
      expect(saved.path).toBe(scenePath);
      expect(saved.format).toBe("c4d");
      expect(existsSync(scenePath)).toBe(true);
    } finally {
      await closeTemporaryDocument();
    }
  });
});
