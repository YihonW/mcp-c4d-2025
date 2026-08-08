import { randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, describe, expect, test } from "vitest";

import {
  closeDocumentIfPresent,
  MCPTestClient,
  printSkipBanner,
  probeBridge,
  requireLiveBridge,
} from "./harness.js";

const SUITE = "foundation-2025";
const CUBE_NAME = "e2e_foundation_cube";
const TARGET_POSITION = [100, 20, -30];
const strictLive = process.env.C4D_MCP_REQUIRE_LIVE === "1";
const truthyEnvironmentValue = (value: string | undefined) =>
  ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
const expectedSecurity = {
  tokenRequired: Boolean(process.env.C4D_MCP_TOKEN?.trim()),
  execPython: truthyEnvironmentValue(process.env.C4D_MCP_ENABLE_EXEC_PYTHON),
};

const probe = await probeBridge(SUITE);
let client: MCPTestClient | null = probe.client ?? null;
let is2025 = false;

if (probe.ready) {
  try {
    const capabilities = await client!.call<{
      c4d_version: number;
      display_version: string;
      compatibility: string;
      platform: string;
      bridge_version: string;
      security: { loopback: boolean; token_required: boolean; exec_python: boolean };
    }>("get_capabilities");
    is2025 = Math.floor(capabilities.c4d_version / 1000) === 2025;
    if (strictLive) {
      requireLiveBridge(probe, capabilities, expectedSecurity);
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
let creationAttempted = false;

type BatchEntry = {
  index: number;
  op: string;
  result?: Record<string, unknown>;
  error?: string;
};

type DocumentEntry = {
  index: number;
  name: string;
  path: string;
  active: boolean;
};

type DocumentList = {
  documents: DocumentEntry[];
  count: number;
};

const withoutTransientIndex = ({ index: _index, ...document }: DocumentEntry) => document;

describe.skipIf(!ready)("Cinema 4D 2025 foundation", () => {
  const c = client!;

  afterAll(async () => {
    try {
      if (creationAttempted) await closeDocumentIfPresent(c, documentName);
    } finally {
      await c.close();
      if (workDir) rmSync(workDir, { recursive: true, force: true });
    }
  });

  test("creates, transforms, verifies, undoes, previews, and saves a temporary scene", async () => {
    const previewPath = path.join(workDir, "foundation-preview.png");
    const scenePath = path.join(workDir, "foundation-scene.c4d");
    const originalDocuments = await c.call<DocumentList>("list_documents");
    const originalActiveDocuments = originalDocuments.documents.filter(
      (document) => document.active,
    );
    expect(originalActiveDocuments).toHaveLength(1);
    const originalActiveDocument = originalActiveDocuments[0];

    creationAttempted = true;
    try {
      const createdDocument = await c.call<{ switched: boolean }>("new_document", {
        name: documentName,
        make_active: false,
      });
      expect(createdDocument.switched).toBe(false);

      const afterCreate = await c.call<DocumentList>("list_documents");
      expect(afterCreate.count).toBe(originalDocuments.count + 1);
      expect(
        afterCreate.documents.filter((document) => document.active).map(withoutTransientIndex),
      ).toEqual([withoutTransientIndex(originalActiveDocument)]);
      expect(afterCreate.documents).toContainEqual(
        expect.objectContaining({ name: documentName, active: false }),
      );

      const failingBatch = await c.call<{ results: BatchEntry[]; count: number }>("batch", {
        document_name: documentName,
        undo_group: false,
        stop_on_error: true,
        ops: [
          {
            op: "sample_transform",
            args: {
              handle: { kind: "object", name: `${CUBE_NAME}_missing` },
              frames: [0],
              space: "local",
            },
          },
        ],
      });
      expect(failingBatch.count).toBe(1);
      expect(failingBatch.results[0].error).toMatch(/resolve|BaseObject/i);

      const afterHandlerError = await c.call<DocumentList>("list_documents");
      expect(
        afterHandlerError.documents
          .filter((document) => document.active)
          .map(withoutTransientIndex),
      ).toEqual([withoutTransientIndex(originalActiveDocument)]);
      expect(
        afterHandlerError.documents
          .filter((document) => document.name !== documentName)
          .map(withoutTransientIndex),
      ).toEqual(originalDocuments.documents.map(withoutTransientIndex));

      const batch = await c.call<{ results: BatchEntry[]; count: number }>(
        "batch",
        {
          document_name: documentName,
          undo_group: false,
          stop_on_error: true,
          ops: [
            {
              op: "create_entity",
              args: { kind: "object", type_id: "cube", name: CUBE_NAME },
            },
            {
              op: "sample_transform",
              args: {
                handle: { kind: "object", name: CUBE_NAME },
                frames: [0],
                space: "local",
              },
            },
            {
              op: "set_transform",
              args: {
                handle: { kind: "object", name: CUBE_NAME },
                pos: TARGET_POSITION,
                space: "local",
              },
            },
            {
              op: "sample_transform",
              args: {
                handle: { kind: "object", name: CUBE_NAME },
                frames: [0],
                space: "local",
              },
            },
            { op: "undo", args: { steps: 1 } },
            {
              op: "sample_transform",
              args: {
                handle: { kind: "object", name: CUBE_NAME },
                frames: [0],
                space: "local",
              },
            },
            {
              op: "preview_render",
              args: { width: 64, height: 64, view: "front", save_path: previewPath },
              timeout_ms: 60_000,
            },
            { op: "get_document_state" },
            {
              op: "save_document",
              args: { path: scenePath, format: "c4d", copy: true },
              timeout_ms: 60_000,
            },
            { op: "get_document_state" },
          ],
        },
        { timeoutMs: 180_000 },
      );

      expect(batch.count).toBe(10);
      expect(batch.results).toHaveLength(10);
      expect(batch.results.filter((entry) => entry.error !== undefined)).toEqual([]);

      const afterSuccessfulBatch = await c.call<DocumentList>("list_documents");
      expect(
        afterSuccessfulBatch.documents
          .filter((document) => document.active)
          .map(withoutTransientIndex),
      ).toEqual([withoutTransientIndex(originalActiveDocument)]);
      expect(
        afterSuccessfulBatch.documents
          .filter((document) => document.name !== documentName)
          .map(withoutTransientIndex),
      ).toEqual(originalDocuments.documents.map(withoutTransientIndex));

      const before = batch.results[1].result as { samples: Array<{ pos: number[] }> };
      const transformed = batch.results[3].result as { samples: Array<{ pos: number[] }> };
      expect(transformed.samples[0].pos).toEqual(TARGET_POSITION);

      const undo = batch.results[4].result as { steps_performed: number };
      expect(undo.steps_performed).toBe(1);
      const reverted = batch.results[5].result as { samples: Array<{ pos: number[] }> };
      expect(reverted.samples[0].pos).toEqual(before.samples[0].pos);

      const preview = batch.results[6].result as {
        image_base64: string;
        width: number;
        height: number;
        saved_path: string;
      };
      expect(preview.image_base64.length).toBeGreaterThan(100);
      expect(preview).toMatchObject({ width: 64, height: 64, saved_path: previewPath });
      expect(existsSync(previewPath)).toBe(true);

      const stateBeforeSave = batch.results[7].result as {
        document_name: string;
        document_path: string;
      };
      const saved = batch.results[8].result as {
        path: string;
        format: string;
        copy: boolean;
      };
      const stateAfterSave = batch.results[9].result as {
        document_name: string;
        document_path: string;
      };
      expect(stateBeforeSave.document_name).toBe(documentName);
      expect(stateAfterSave.document_name).toBe(stateBeforeSave.document_name);
      expect(stateAfterSave.document_path).toBe(stateBeforeSave.document_path);
      expect(saved.path).toBe(scenePath);
      expect(saved.format).toBe("c4d");
      expect(saved.copy).toBe(true);
      expect(existsSync(scenePath)).toBe(true);

      await closeDocumentIfPresent(c, documentName);
      creationAttempted = false;
      expect(await c.call<DocumentList>("list_documents")).toEqual(originalDocuments);
    } finally {
      if (creationAttempted) await closeDocumentIfPresent(c, documentName);
    }
  });
});
