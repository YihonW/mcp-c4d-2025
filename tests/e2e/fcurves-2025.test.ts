import { randomUUID } from "node:crypto";
import { afterAll, describe, expect, test } from "vitest";

import {
  closeDocumentIfPresent,
  MCPTestClient,
  printSkipBanner,
  probeBridge,
  requireLiveBridge,
} from "./harness.js";

const SUITE = "fcurves-2025";
const strictLive = process.env.C4D_MCP_REQUIRE_LIVE === "1";
// Even the broad E2E opt-in must not start this production-path test.
const probe: Awaited<ReturnType<typeof probeBridge>> = strictLive
  ? await probeBridge(SUITE)
  : { ready: false, reason: "C4D_MCP_REQUIRE_LIVE=1 is required" };
let client: MCPTestClient | null = probe.client ?? null;
let ready = false;

if (!strictLive) printSkipBanner(SUITE, probe.reason!, "F-Curve live test is disabled");
if (probe.ready) {
  try {
    const capabilities = await client!.call<{
      c4d_version: number;
      display_version: string;
      compatibility: string;
      platform: string;
      bridge_version: string;
      security: { loopback: boolean; token_required: boolean; exec_python: boolean };
      features?: Record<string, boolean>;
    }>("get_capabilities");
    requireLiveBridge(probe, capabilities, { tokenRequired: true, execPython: false });
    if (capabilities.bridge_version !== "0.5.0") {
      throw new Error("F-Curve test requires bridge 0.5.0; refusing to create a test document");
    }
    for (const feature of ["animation_fcurves", "animation_descid_paths"]) {
      if (capabilities.features?.[feature] !== true) {
        throw new Error(`Installed bridge lacks ${feature}; refusing to create a test document`);
      }
    }
    ready = true;
  } catch (error) {
    await client!.close();
    client = null;
    throw error;
  }
}

type ObjectHandle = { kind: "object"; name: string; path: string };
type DocumentEntry = { index: number; name: string; path: string; active: boolean };
type DocumentList = { documents: DocumentEntry[]; count: number };
type BatchResult<T> = { results: Array<{ result?: T; error?: string }>; count: number };
type Tangent = { dt_frames: number; dv: number };
type Curve = {
  document_name: string;
  handle: ObjectHandle;
  path: number[][];
  fps: number;
  key_count: number;
  keys: Array<{
    key_index: number;
    frame: number;
    value: number;
    interp: string;
    left: Tangent;
    right: Tangent;
    tangent_mode: "auto" | "manual";
  }>;
  before: string;
  after: string;
  samples: Array<{ frame: number; value: number }>;
};

const stableDocument = ({ index: _index, ...entry }: DocumentEntry) => entry;
const suffix = randomUUID().slice(0, 8);
const documentName = `e2e_fcurves_2025_${suffix}`;

afterAll(async () => {
  await client?.close();
});

describe.skipIf(!ready)("Cinema 4D 2025.3.2 isolated F-Curve workflow", () => {
  const c = client!;

  async function scoped<T>(op: string, args: Record<string, unknown> = {}): Promise<T> {
    const batch = await c.call<BatchResult<T>>("batch", {
      document_name: documentName,
      undo_group: false,
      stop_on_error: true,
      ops: [{ op, args }],
    });
    expect(batch.results, op).toHaveLength(1);
    expect(batch.results[0].error, op).toBeUndefined();
    expect(batch.results[0].result, op).toBeDefined();
    return batch.results[0].result!;
  }

  test(
    "verifies effective tangents, undo, subframe transforms and extrapolation in one document",
    { timeout: 300_000, retry: 0 },
    async () => {
      const original = await c.call<DocumentList>("list_documents");
      const originalActive = original.documents.filter((entry) => entry.active).map(stableDocument);
      expect(originalActive).toHaveLength(1);
      expect(original.documents.some((entry) => entry.name === documentName)).toBe(false);
      const originalState = await c.call("get_document_state");
      let creationAttempted = false;
      const failures: unknown[] = [];

      try {
        const objects = await c.call<{ entities: unknown[] }>("list_entities", {
          kind: "object",
          max_depth: 0,
        });
        const materials = await c.call<{ entities: unknown[] }>("list_entities", {
          kind: "material",
        });
        if (objects.entities.length === 0 && materials.entities.length === 0) {
          throw new Error(
            "Active document has no objects or materials; refusing insertion that could replace a blank user document",
          );
        }
        expect(
          (await c.call<DocumentList>("list_documents")).documents.map(stableDocument),
        ).toEqual(original.documents.map(stableDocument));
        creationAttempted = true;
        const created = await c.call<{ switched: boolean }>("new_document", {
          name: documentName,
          make_active: false,
        });
        expect(created.switched).toBe(false);
        const afterCreate = await c.call<DocumentList>("list_documents");
        expect(afterCreate.count).toBe(original.count + 1);
        expect(afterCreate.documents.filter((entry) => entry.active).map(stableDocument)).toEqual(
          originalActive,
        );
        await scoped("set_document", { fps: 24, frame_start: 0, frame_end: 24, current_frame: 0 });
        const handle = (
          await scoped<{ handle: ObjectHandle }>("create_entity", {
            kind: "object",
            type_id: "null",
            name: `e2e_fcurve_control_${suffix}`,
          })
        ).handle;
        const control = await scoped<{ desc_id: number[][]; dtype: string }>("add_user_data", {
          handle,
          name: `e2e_fcurve_value_${suffix}`,
          dtype: "real",
          value: 0,
        });
        expect(control.dtype).toBe("real");
        expect(control.desc_id).toHaveLength(2);
        expect(control.desc_id.every((level) => level.length === 3)).toBe(true);
        const selector = { document_name: documentName, handle, path: control.desc_id };
        for (const [index, frame] of [0, 12, 24].entries()) {
          await scoped("set_keyframe", {
            handle,
            path: control.desc_id,
            frame,
            value: [0, 12, 0][index],
            interp: "linear",
          });
        }
        const samples = [3, 6, 15];
        const read = (sample_frames = samples) =>
          scoped<Curve>("get_fcurve", { ...selector, sample_frames });
        const initial = await read();
        expect(initial.document_name).toBe(documentName);
        expect(initial.path).toEqual(control.desc_id);
        expect(initial.fps).toBe(24);
        expect(initial.key_count).toBe(3);
        expect(initial.keys.map(({ frame, value }) => ({ frame, value }))).toEqual([
          { frame: 0, value: 0 },
          { frame: 12, value: 12 },
          { frame: 24, value: 0 },
        ]);
        for (const [index, expected] of [3, 6, 9].entries()) {
          expect(initial.samples[index].value).toBeCloseTo(expected, 5);
        }
        const testState = await scoped("get_document_state");

        const manualEdits = [0, 1, 2].map((key_index) => ({
          key_index,
          interp: "spline",
          tangent_mode: "manual",
          left: { dt_frames: -4, dv: key_index === 0 ? -12 : 0 },
          right: { dt_frames: 4, dv: key_index === 0 ? 12 : 0 },
        }));
        await scoped("edit_fcurve_keys", { ...selector, edits: manualEdits });
        const manual = await read();
        expect(manual.keys.every((key) => key.tangent_mode === "manual")).toBe(true);
        expect(manual.keys.every((key) => key.interp === "spline")).toBe(true);
        expect(manual.keys[0].right.dt_frames).toBeCloseTo(4, 6);
        expect(manual.keys[0].right.dv).toBeCloseTo(12, 6);
        expect(manual.keys[1].left.dt_frames).toBeCloseTo(-4, 6);
        expect(manual.keys[1].left.dv).toBeCloseTo(0, 6);
        // Equally spaced Bezier X controls make t = frame/12 in this segment.
        expect(manual.samples[0].value).toBeCloseTo(6.9375, 4);
        expect(manual.samples[1].value).toBeCloseTo(10.5, 4);
        expect(
          (await scoped<{ steps_performed: number }>("undo", { steps: 1 })).steps_performed,
        ).toBe(1);
        expect(await read()).toEqual(initial);

        await scoped("edit_fcurve_keys", { ...selector, edits: manualEdits });
        await scoped("edit_fcurve_keys", {
          ...selector,
          edits: [{ key_index: 0, tangent_mode: "auto" }],
        });
        const automatic = await read();
        expect(automatic.keys[0].tangent_mode).toBe("auto");
        // Cinema 4D automatic first/last-key tangents are horizontal.
        expect(automatic.keys[0].right.dv).toBeCloseTo(0, 5);
        expect(automatic.samples[0].value).toBeGreaterThan(0);
        expect(automatic.samples[0].value).toBeLessThan(12);
        expect(Math.abs(automatic.samples[0].value - manual.samples[0].value)).toBeGreaterThan(1);
        await scoped("undo", { steps: 1 });
        expect(await read()).toEqual(manual);

        await scoped("transform_fcurve", {
          ...selector,
          time_scale: 0.5,
          time_offset_frames: 0.25,
          value_scale: 2,
          value_offset: 1,
        });
        const transformed = await read([1.75, 3.25, 7.75]);
        for (const [index, expected] of [0.25, 6.25, 12.25].entries()) {
          expect(transformed.keys[index].frame).toBeCloseTo(expected, 6);
        }
        expect(transformed.keys.map((key) => key.value)).toEqual([1, 25, 1]);
        expect(transformed.keys[0].right.dt_frames).toBeCloseTo(2, 6);
        expect(transformed.keys[0].right.dv).toBeCloseTo(24, 6);
        expect(transformed.keys[1].left.dt_frames).toBeCloseTo(-2, 6);
        expect(transformed.samples[0].value).toBeCloseTo(14.875, 4);
        const collision = await c.call<BatchResult<Curve>>("batch", {
          document_name: documentName,
          undo_group: false,
          stop_on_error: true,
          ops: [
            {
              op: "transform_fcurve",
              args: { ...selector, key_indices: [0], time_offset_frames: 6 },
            },
          ],
        });
        expect(collision.results).toHaveLength(1);
        expect(collision.results[0].error).toMatch(/colli/i);
        expect(collision.results[0].result).toBeUndefined();
        expect(await read([1.75, 3.25, 7.75])).toEqual(transformed);
        // The rejected collision must not have inserted a new undo item either.
        await scoped("undo", { steps: 1 });
        expect(await read()).toEqual(manual);

        await scoped("edit_fcurve_keys", {
          ...selector,
          edits: [0, 1, 2].map((key_index) => ({
            key_index,
            value: key_index * 12,
            interp: "linear",
          })),
        });
        const extrapolationCases = [
          ["constant", [0, 24]],
          ["linear", [-6, 30]],
          ["repeat", [18, 6]],
          ["offset_repeat", [-6, 30]],
          ["oscillate", [6, 18]],
        ] as const;
        for (const [mode, expected] of extrapolationCases) {
          await scoped("set_track_extrapolation", { ...selector, before: mode, after: mode });
          const result = await read([-6, 30]);
          expect(result.before).toBe(mode);
          expect(result.after).toBe(mode);
          expect(result.keys.map((key) => key.frame)).toEqual([0, 12, 24]);
          expect(result.samples.map((sample) => sample.frame)).toEqual([-6, 30]);
          for (const [index, value] of expected.entries()) {
            expect(
              result.samples[index].value,
              `${mode} at ${result.samples[index].frame}`,
            ).toBeCloseTo(value, 4);
          }
        }
        expect(await scoped("get_document_state")).toEqual(testState);
      } catch (error) {
        failures.push(error);
      } finally {
        try {
          if (creationAttempted) await closeDocumentIfPresent(c, documentName);
          const after = await c.call<DocumentList>("list_documents");
          expect(after.count).toBe(original.count);
          expect(after.documents.map(stableDocument)).toEqual(
            original.documents.map(stableDocument),
          );
          expect(after.documents.filter((entry) => entry.active).map(stableDocument)).toEqual(
            originalActive,
          );
          expect(await c.call("get_document_state")).toEqual(originalState);
        } catch (error) {
          failures.push(error);
        }
      }
      if (failures.length === 1) throw failures[0];
      if (failures.length > 1) throw new AggregateError(failures, "F-Curve test or cleanup failed");
    },
  );
});
