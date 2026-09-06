import { createHash, randomUUID } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { afterAll, describe, expect, test } from "vitest";

import {
  closeDocumentIfPresent,
  MCPTestClient,
  printSkipBanner,
  probeBridge,
  requireLiveBridge,
  requireRedshiftCapabilities,
} from "./harness.js";

const SUITE = "workflow-2025";
const strictLive = process.env.C4D_MCP_REQUIRE_LIVE === "1";
// This production-path suite requires the strict flag, even when other E2E suites are enabled.
const probe: Awaited<ReturnType<typeof probeBridge>> = strictLive
  ? await probeBridge(SUITE)
  : { ready: false, reason: "C4D_MCP_REQUIRE_LIVE=1 is required" };
let client: MCPTestClient | null = probe.client ?? null;
let ready = false;

if (!strictLive) printSkipBanner(SUITE, probe.reason!, "Workflow live test is disabled");
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
    for (const feature of ["rs_render_frame", "animation_descid_paths", "parameter_links"]) {
      if (capabilities.features?.[feature] !== true) {
        throw new Error(`Installed bridge lacks ${feature}; refusing to create a test document`);
      }
    }
    requireRedshiftCapabilities(await client!.call("rs_get_capabilities"));
    ready = true;
  } catch (error) {
    await client!.close();
    client = null;
    throw error;
  }
}

type ObjectHandle = { kind: "object"; name: string; path: string };
type DescPath = number[][];
type DocumentEntry = { index: number; name: string; path: string; active: boolean };
type DocumentList = { documents: DocumentEntry[]; count: number };
type BatchResult<T> = { results: Array<{ result?: T; error?: string }>; count: number };
type ParameterResult = { applied: unknown[]; errors: Array<{ error: string }> };
type ParameterValues = { values: Array<{ path: unknown; value?: unknown; error?: string }> };
type TransformSamples = {
  samples: Array<{ frame: number; pos: number[]; rot: number[] }>;
};
type SequenceStatus = {
  job_id: string;
  state: "running" | "cancelling" | "cancelled" | "completed" | "failed" | "uncertain";
  settled: boolean;
  frames: number[];
  completed: Array<{
    frame: number;
    path: string;
    size: number;
    sha256: string;
    width: number;
    height: number;
  }>;
  error?: string;
};

const stableDocument = ({ index: _index, ...entry }: DocumentEntry) => entry;
const suffix = randomUUID().slice(0, 8);
const documentName = `e2e_workflow_2025_${suffix}`;
let workDir = "";
let preserveArtifacts = false;

afterAll(async () => {
  await client?.close();
  if (workDir && process.env.C4D_MCP_KEEP_WORKFLOW_OUTPUT === "1") {
    console.log(`[${SUITE}] Retained verification output: ${workDir}`);
  } else if (workDir && !preserveArtifacts) rmSync(workDir, { recursive: true, force: true });
});

describe.skipIf(!ready)("Cinema 4D 2025.3.2 isolated mechanical-arm workflow", () => {
  const c = client!;

  async function scoped<T>(op: string, args: Record<string, unknown> = {}): Promise<T> {
    const batch = await c.call<BatchResult<T>>(
      "batch",
      {
        document_name: documentName,
        undo_group: false,
        stop_on_error: true,
        ops: [{ op, args }],
      },
      { timeoutMs: 90_000 },
    );
    expect(batch.results, op).toHaveLength(1);
    expect(batch.results[0].error, op).toBeUndefined();
    expect(batch.results[0].result, op).toBeDefined();
    return batch.results[0].result!;
  }

  test(
    "models, links, animates and verifies seven 128px PNG frames in exactly one test document",
    { timeout: 1_920_000, retry: 0 },
    async () => {
      workDir = mkdtempSync(path.join(tmpdir(), "c4d-mcp-workflow-2025-"));
      const texturePath = path.join(workDir, "one-pixel.png");
      const scenePath = path.join(workDir, "mechanical-arm.c4d");
      const outputDirectory = path.join(workDir, "sequence");
      writeFileSync(
        texturePath,
        Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=",
          "base64",
        ),
      );
      const original = await c.call<DocumentList>("list_documents");
      const originalActive = original.documents.filter((entry) => entry.active).map(stableDocument);
      expect(originalActive).toHaveLength(1);
      let creationAttempted = false;
      let safeToClose = true;
      let jobId: string | undefined;
      const failures: unknown[] = [];

      try {
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

        const root = (
          await scoped<{ handle: ObjectHandle }>("create_entity", {
            kind: "object",
            type_id: "null",
            name: `e2e_shoulder_${suffix}`,
            position: [0, 75, 0],
          })
        ).handle;
        const joint = (
          await scoped<{ handle: ObjectHandle }>("create_entity", {
            kind: "object",
            type_id: "null",
            name: `e2e_elbow_${suffix}`,
            parent: root,
            position: [80, 0, 0],
          })
        ).handle;
        const meshes: ObjectHandle[] = [];
        for (const [name, parent, length] of [
          [`e2e_upper_arm_${suffix}`, root, 80],
          [`e2e_forearm_${suffix}`, joint, 70],
        ] as const) {
          const primitive = (
            await scoped<{ handle: ObjectHandle }>("create_entity", {
              kind: "object",
              type_id: "cube",
              name,
              parent,
              position: [length / 2, 0, 0],
              params: { "1100": [length, 14, 18] }, // PRIM_CUBE_LEN, inspected by get_mesh below.
            })
          ).handle;
          const editable = await scoped<{ ok: boolean; results: Array<{ handle: ObjectHandle }> }>(
            "modeling_command",
            { command: "make_editable", targets: [primitive] },
          );
          expect(editable.ok).toBe(true);
          expect(editable.results).toHaveLength(1);
          const meshHandle = editable.results[0].handle;
          expect(meshHandle.path).toBe(`${parent.path}/${name}`);
          const mesh = await scoped<{
            type: string;
            point_count: number;
            polygon_count: number;
            points: number[][];
          }>("get_mesh", { handle: meshHandle, max_points: 100, max_polys: 100 });
          expect(mesh).toMatchObject({ type: "polygon", point_count: 8, polygon_count: 6 });
          expect(mesh.points).toHaveLength(8);
          expect(
            Math.max(...mesh.points.map((p) => p[0])) - Math.min(...mesh.points.map((p) => p[0])),
          ).toBeCloseTo(length, 5);
          meshes.push(meshHandle);
        }

        for (const [handle, values] of [
          [root, [-0.35, 0.7, -0.35]],
          [joint, [0, -0.8, 0]],
        ] as const) {
          for (const [index, frame] of [0, 12, 24].entries()) {
            await scoped("set_keyframe", {
              handle,
              param_id: 904,
              component: "z",
              frame,
              value: values[index],
              interp: "linear",
            });
          }
        }
        const rotation = await scoped<TransformSamples>("sample_transform", {
          handle: root,
          frames: [0, 6, 12, 24],
          space: "local",
          restore_time: true,
        });
        expect(rotation.samples.map((s) => s.frame)).toEqual([0, 6, 12, 24]);
        for (const [index, expected] of [-0.35, 0.175, 0.7, -0.35].entries()) {
          // MatrixToHPB may normalize negative angles into [0, 2*pi).
          const difference = rotation.samples[index].rot[2] - expected;
          expect(Math.atan2(Math.sin(difference), Math.cos(difference))).toBeCloseTo(0, 4);
        }
        const movement = await scoped<TransformSamples>("sample_transform", {
          handle: meshes[1],
          frames: [0, 6, 12],
          space: "global",
          restore_time: true,
        });
        expect(movement.samples).toHaveLength(3);
        expect(
          Math.hypot(...movement.samples[2].pos.map((v, i) => v - movement.samples[0].pos[i])),
        ).toBeGreaterThan(20);

        const control = await scoped<{ desc_id: DescPath; dtype: string }>("add_user_data", {
          handle: root,
          name: `e2e_drive_${suffix}`,
          dtype: "real",
          value: 0.25,
        });
        expect(control.dtype).toBe("real");
        expect(control.desc_id).toHaveLength(2);
        expect(control.desc_id.every((level) => level.length === 3)).toBe(true);
        const controlWrite = await scoped<ParameterResult>("set_params", {
          handle: root,
          values: [{ path: control.desc_id, value: 0.5 }],
        });
        expect(controlWrite.errors).toEqual([]);
        expect(controlWrite.applied).toHaveLength(1);
        const controlRead = await scoped<ParameterValues>("get_params", {
          handle: root,
          ids: [control.desc_id],
        });
        expect(controlRead.values[0].error).toBeUndefined();
        expect(controlRead.values[0].value).toBe(0.5);
        for (const [index, frame] of [0, 12, 24].entries()) {
          await scoped("set_keyframe", {
            handle: root,
            path: control.desc_id,
            frame,
            value: [0, 1, 0][index],
            interp: "linear",
          });
        }
        const controlKeys = await scoped<{ keys: Array<{ frame: number; value: number }> }>(
          "get_keyframes",
          {
            handle: root,
            path: control.desc_id,
          },
        );
        expect(controlKeys.keys.map(({ frame, value }) => ({ frame, value }))).toEqual([
          { frame: 0, value: 0 },
          { frame: 12, value: 1 },
          { frame: 24, value: 0 },
        ]);

        const link = await scoped<{ desc_id: DescPath }>("add_user_data", {
          handle: root,
          name: `e2e_target_${suffix}`,
          dtype: "link",
        });
        const linkWrite = await scoped<ParameterResult>("set_params", {
          handle: root,
          values: [{ path: link.desc_id, value: { link: joint } }],
        });
        expect(linkWrite.errors).toEqual([]);
        expect(linkWrite.applied).toHaveLength(1);
        const linkRead = await scoped<ParameterValues>("get_params", {
          handle: root,
          ids: [link.desc_id],
        });
        expect(linkRead.values[0].error).toBeUndefined();
        expect(linkRead.values[0].value).toMatchObject({ __c4d__: "BaseObject", name: joint.name });
        const badLink = await scoped<ParameterResult>("set_params", {
          handle: root,
          values: [
            { path: link.desc_id, value: { link: { kind: "object", path: `/missing_${suffix}` } } },
          ],
        });
        expect(badLink.applied).toEqual([]);
        expect(badLink.errors).toHaveLength(1);
        expect(badLink.errors[0].error).toMatch(/not resolved/);
        expect(await scoped("get_params", { handle: root, ids: [link.desc_id] })).toEqual(linkRead);

        const materialName = `e2e_workflow_material_${suffix}`;
        await c.call("rs_create_material", { document_name: documentName, name: materialName });
        await c.call("rs_set_material_pbr", {
          document_name: documentName,
          material: { kind: "material", name: materialName },
          base_color: [0.12, 0.45, 0.75],
          metalness: 0.2,
          roughness: 0.35,
        });
        for (const object of meshes) {
          await scoped("assign_material", {
            object,
            material: { kind: "material", name: materialName },
            projection: "cubic",
          });
        }
        await c.call("rs_create_light", {
          document_name: documentName,
          name: `e2e_workflow_area_${suffix}`,
          type: "area",
          position: [20, 180, -150],
          intensity: 100,
        });
        await c.call("rs_create_light", {
          document_name: documentName,
          name: `e2e_workflow_dome_${suffix}`,
          type: "dome",
          dome_texture: texturePath,
          intensity: 0.5,
        });
        const cameraName = `e2e_workflow_camera_${suffix}`;
        await c.call("rs_set_camera", {
          document_name: documentName,
          name: cameraName,
          position: [60, 75, -460],
          rotation: [0, 0, 0],
        });
        const camera = await scoped<{ updated: { active_camera: string } }>("set_document", {
          active_camera: cameraName,
          current_frame: 0,
        });
        expect(camera.updated.active_camera).toBe(cameraName);
        const renderDataName = `e2e_workflow_render_${suffix}`;
        await c.call("rs_configure_render", {
          document_name: documentName,
          name: renderDataName,
          width: 128,
          height: 128,
          frame: 0,
          output_format: "png",
          beauty_path: path.join(workDir, "unused-beauty.png"),
          make_active: false,
          redshift_params: { "1101": 4, "1102": 16, "1107": false },
        });
        const aovs = await c.call<{ count: number }>("rs_list_aovs", {
          document_name: documentName,
          render_data_name: renderDataName,
        });
        expect(aovs.count).toBe(0);
        const beforeSave = await scoped("get_document_state");
        const saved = await scoped<{ path: string; copy: boolean }>("save_document", {
          path: scenePath,
          format: "c4d",
          copy: true,
        });
        expect(saved).toMatchObject({ path: scenePath, copy: true });
        expect(statSync(scenePath).size).toBeGreaterThan(0);
        expect(await scoped("get_document_state")).toEqual(beforeSave);

        const frames = [0, 2, 4, 6, 8, 10, 12];
        // From submission until a definite settled outcome, never close the scene on failure.
        safeToClose = false;
        const started = await c.call<SequenceStatus>("rs_render_sequence", {
          document_name: documentName,
          render_data_name: renderDataName,
          output_directory: outputDirectory,
          frames,
          force: true,
        });
        jobId = started.job_id;
        expect(jobId).toMatch(/^[0-9a-f-]{36}$/i);
        const deadline = Date.now() + 1_800_000;
        let status = started;
        while (true) {
          status = await c.call<SequenceStatus>("rs_sequence_status", { job_id: jobId });
          if (status.settled && !["running", "cancelling"].includes(status.state)) {
            safeToClose = status.state !== "uncertain";
            expect(status.state, JSON.stringify(status)).toBe("completed");
            break;
          }
          if (Date.now() >= deadline)
            throw new Error(`Sequence did not settle before deadline: ${JSON.stringify(status)}`);
          await delay(1000);
        }
        expect(status.frames).toEqual(frames);
        expect(status.completed.map((output) => output.frame)).toEqual(frames);
        const hashes = new Set<string>();
        for (const output of status.completed) {
          expect(path.dirname(output.path)).toBe(outputDirectory);
          const bytes = readFileSync(output.path);
          expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
          expect(bytes.subarray(12, 16).toString("ascii")).toBe("IHDR");
          expect(bytes.subarray(-8, -4).toString("ascii")).toBe("IEND");
          expect(bytes.readUInt32BE(16)).toBe(128);
          expect(bytes.readUInt32BE(20)).toBe(128);
          expect(output).toMatchObject({ width: 128, height: 128, size: bytes.length });
          const hash = createHash("sha256").update(bytes).digest("hex");
          expect(output.sha256).toBe(hash);
          hashes.add(hash);
        }
        expect(
          hashes.size,
          "Animation frames must not all contain identical PNG bytes",
        ).toBeGreaterThan(1);
        const manifest = JSON.parse(
          readFileSync(path.join(outputDirectory, "manifest.json"), "utf8"),
        );
        expect(manifest).toMatchObject({
          job_id: jobId,
          state: "completed",
          frames,
          completed: status.completed,
        });
        expect(await scoped("get_document_state")).toEqual(beforeSave);
      } catch (error) {
        failures.push(error);
      } finally {
        if (!safeToClose) {
          preserveArtifacts = true;
          console.error(
            `[${SUITE}] Render outcome uncertain: preserving document ${documentName}, job ${jobId ?? "unknown"}, artifacts ${workDir}. Do not retry automatically.`,
          );
        } else if (creationAttempted) {
          try {
            await closeDocumentIfPresent(c, documentName);
            const restored = await c.call<DocumentList>("list_documents");
            expect(restored.count).toBe(original.count);
            expect(restored.documents.map(stableDocument)).toEqual(
              original.documents.map(stableDocument),
            );
          } catch (error) {
            preserveArtifacts = true;
            console.error(
              `[${SUITE}] Cleanup failed; preserving artifacts ${workDir} for document ${documentName}.`,
            );
            failures.push(error);
          }
        }
      }
      if (failures.length === 1) throw failures[0];
      if (failures.length > 1) throw new AggregateError(failures, "Workflow and cleanup failed");
    },
  );
});
