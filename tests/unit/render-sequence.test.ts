import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { crc32 } from "node:zlib";
import { afterEach, expect, test } from "vitest";
import { C4DCommandError, type C4DClient } from "../../src/c4d-client.js";
import { RenderSequences } from "../../src/render-sequence.js";
import { ALL_TOOLS } from "../../src/tools/index.js";
import {
  rsRenderSequenceTool,
  rsSequenceControlTool,
  rsSequenceStatusTool,
} from "../../src/tools/rs-render-sequence.js";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=",
  "base64",
);
const directories: string[] = [];
async function location() {
  const root = await mkdtemp(path.join(tmpdir(), "c4d-sequence-unit-"));
  directories.push(root);
  return path.join(root, "sequence");
}
afterEach(async () => {
  for (const directory of directories.splice(0))
    await rm(directory, { recursive: true, force: true });
});

class FakeClient {
  supported = true;
  calls: Record<string, unknown>[] = [];
  gate?: Promise<void>;
  failure?: string;
  invalidPng = false;
  wrongFrame = false;
  output?: Buffer;
  async request(command: string, params: Record<string, unknown> = {}) {
    if (command === "get_capabilities") return { features: { rs_render_frame: this.supported } };
    expect(command).toBe("rs_render");
    this.calls.push(params);
    await this.gate;
    if (this.failure) {
      if (this.failure.startsWith("Redshift") || this.failure.startsWith("command '"))
        throw new C4DCommandError(this.failure);
      throw new Error(this.failure);
    }
    const data = this.output ?? (this.invalidPng ? Buffer.from("not a png") : png);
    await writeFile(String(params.output_path), data, { flag: "wx" });
    return {
      frame: this.wrongFrame ? -1 : params.frame,
      width: 1,
      height: 1,
      beauty: { path: params.output_path, size: data.length },
      expected_missing: [],
    };
  }
}
function setup() {
  const client = new FakeClient();
  const manager = new RenderSequences(client as unknown as C4DClient);
  return { client, manager };
}
async function waitFor(check: () => boolean) {
  await expect.poll(check, { timeout: 4000, interval: 10 }).toBe(true);
}
const input = (directory: string) => ({
  document_name: "Scene",
  render_data_name: "RS",
  output_directory: directory,
  frames: [2, 0, 1],
});

test("registers sequence start/status/control", () => {
  for (const tool of [rsRenderSequenceTool, rsSequenceStatusTool, rsSequenceControlTool])
    expect(ALL_TOOLS).toContain(tool);
});

test("renders sorted unique frames, validates PNGs and persists a complete manifest", async () => {
  const { client, manager } = setup();
  const directory = await location();
  const job = await manager.start(input(directory));
  await waitFor(() => manager.status(job.job_id).settled);
  const status = manager.status(job.job_id);
  expect(status.state).toBe("completed");
  expect(status.completed.map((output) => output.frame)).toEqual([0, 1, 2]);
  expect(
    client.calls.every((call) => call.sequence_frame === true && call.overwrite === false),
  ).toBe(true);
  expect(status.completed.every((output) => output.sha256.length === 64)).toBe(true);
  const manifest = JSON.parse(await readFile(path.join(directory, "manifest.json"), "utf8"));
  expect(manifest.state).toBe("completed");
  expect(manifest.completed).toHaveLength(3);
});

test("rejects unsupported bridge before creating output directory", async () => {
  const { client, manager } = setup();
  client.supported = false;
  const directory = await location();
  await expect(manager.start(input(directory))).rejects.toThrow("Installed bridge lacks");
  await expect(readFile(path.join(directory, "manifest.json"))).rejects.toThrow();
  expect(client.calls).toHaveLength(0);
});

test("rejects duplicate/out-of-range frames, excessive jobs and existing output directories", async () => {
  const { manager } = setup();
  const directory = await location();
  for (const frames of [
    [],
    [0, 0],
    [-1],
    [1.5],
    [1_000_001],
    Array.from({ length: 301 }, (_, i) => i),
  ]) {
    await expect(manager.start({ ...input(directory), frames })).rejects.toThrow(
      "Require unique frames",
    );
  }
  await expect(manager.start({ ...input("relative"), frames: [0] })).rejects.toThrow("absolute");
  await expect(manager.start(input(path.dirname(directory)))).rejects.toThrow();
});

test("cancels only after the in-flight frame and resumes without replacing completed output", async () => {
  const { client, manager } = setup();
  let release!: () => void;
  client.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const job = await manager.start(input(await location()));
  await waitFor(() => client.calls.length === 1);
  expect(manager.cancel(job.job_id).state).toBe("cancelling");
  await expect(manager.start(input(await location()))).rejects.toThrow("already active");
  release();
  await waitFor(() => manager.status(job.job_id).settled);
  expect(manager.status(job.job_id).state).toBe("cancelled");
  expect(client.calls).toHaveLength(1);
  await manager.resume(job.job_id);
  await waitFor(() => manager.status(job.job_id).settled);
  expect(manager.status(job.job_id).state).toBe("completed");
  expect(client.calls.map((call) => call.frame)).toEqual([0, 1, 2]);
});

test("refuses resume when a completed PNG changed", async () => {
  const { client, manager } = setup();
  let release!: () => void;
  client.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const job = await manager.start(input(await location()));
  await waitFor(() => client.calls.length === 1);
  manager.cancel(job.job_id);
  release();
  await waitFor(() => manager.status(job.job_id).settled);
  // Add a valid ancillary text chunk, so the PNG is readable but its hash changes.
  const comment = Buffer.from("Comment\0changed");
  const chunk = Buffer.alloc(comment.length + 12);
  chunk.writeUInt32BE(comment.length);
  chunk.write("tEXt", 4);
  comment.copy(chunk, 8);
  chunk.writeUInt32BE(crc32(chunk.subarray(4, -4)), chunk.length - 4);
  const altered = Buffer.concat([png.subarray(0, 33), chunk, png.subarray(33)]);
  await writeFile(manager.status(job.job_id).completed[0].path, altered);
  await expect(manager.resume(job.job_id)).rejects.toThrow("changed");
  expect(client.calls).toHaveLength(1);
});

test("resume manifest failure releases the queue instead of leaving a permanently busy job", async () => {
  const { client, manager } = setup();
  let release!: () => void;
  client.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const directory = await location();
  const job = await manager.start(input(directory));
  await waitFor(() => client.calls.length === 1);
  manager.cancel(job.job_id);
  release();
  await waitFor(() => manager.status(job.job_id).settled);
  expect(manager.status(job.job_id).state).toBe("cancelled");

  // A directory at the temporary-file path reliably makes manifest writes fail.
  await mkdir(path.join(directory, ".manifest.tmp"));
  await expect(manager.resume(job.job_id)).rejects.toThrow();
  expect(manager.status(job.job_id)).toMatchObject({ state: "failed", settled: true });
  expect(manager.status(job.job_id).error).toBeTruthy();
  expect(client.calls).toHaveLength(1);

  const next = await manager.start({ ...input(await location()), frames: [5] });
  await waitFor(() => manager.status(next.job_id).settled);
  expect(manager.status(next.job_id).state).toBe("completed");
});

test("cancellation during resume file verification prevents any further render", async () => {
  const { client, manager } = setup();
  let release!: () => void;
  client.gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const job = await manager.start(input(await location()));
  await waitFor(() => client.calls.length === 1);
  manager.cancel(job.job_id);
  release();
  await waitFor(() => manager.status(job.job_id).settled);

  // resume yields while checking the completed PNG; cancel before that IO settles.
  const resumed = manager.resume(job.job_id);
  expect(manager.status(job.job_id).settled).toBe(false);
  expect(manager.cancel(job.job_id).state).toBe("cancelling");
  await resumed;
  await waitFor(() => manager.status(job.job_id).settled);
  expect(manager.status(job.job_id).state).toBe("cancelled");
  expect(client.calls).toHaveLength(1);
});

test.each([
  "Redshift render failed with code 1",
  "socket closed",
  "client closed",
  "write EPIPE",
  "Command timed out after 1800000ms",
  "command 'rs_render' timed out",
])("stops on %s without retries", async (failure) => {
  const { client, manager } = setup();
  client.failure = failure;
  const job = await manager.start(input(await location()));
  await waitFor(() => manager.status(job.job_id).settled);
  expect(manager.status(job.job_id).state).toBe(
    failure.startsWith("Redshift") ? "failed" : "uncertain",
  );
  expect(client.calls).toHaveLength(1);
  await expect(manager.resume(job.job_id)).rejects.toThrow();
  if (!failure.startsWith("Redshift")) {
    await expect(manager.start(input(await location()))).rejects.toThrow("already active");
    expect(client.calls).toHaveLength(1);
  }
});

test.each(["missing IDAT", "corrupt CRC"])("rejects a PNG with %s", async (mode) => {
  const { client, manager } = setup();
  if (mode === "missing IDAT") {
    // Complete IHDR and IEND chunks with valid CRCs, but no pixel data.
    client.output = Buffer.concat([png.subarray(0, 33), png.subarray(56)]);
  } else {
    client.output = Buffer.from(png);
    client.output[45] ^= 1;
  }
  const job = await manager.start(input(await location()));
  await waitFor(() => manager.status(job.job_id).settled);
  const status = manager.status(job.job_id);
  expect(status.state).toBe("failed");
  expect(status.error).toMatch(mode === "missing IDAT" ? /Incomplete PNG/ : /CRC mismatch/);
  expect(status.completed).toEqual([]);
  expect(client.calls).toHaveLength(1);
});

test.each(["invalidPng", "wrongFrame"] as const)(
  "rejects %s without scheduling more frames",
  async (mode) => {
    const { client, manager } = setup();
    client[mode] = true;
    const job = await manager.start(input(await location()));
    await waitFor(() => manager.status(job.job_id).settled);
    expect(manager.status(job.job_id).state).toBe("failed");
    expect(manager.status(job.job_id).completed).toEqual([]);
    expect(client.calls).toHaveLength(1);
  },
);
