import { createHash, randomUUID } from "node:crypto";
import { lstat, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { crc32 } from "node:zlib";
import { C4DCommandError, type C4DClient } from "./c4d-client.js";

export type SequenceInput = {
  document_name: string;
  render_data_name: string;
  output_directory: string;
  frames: number[];
};
type Output = {
  frame: number;
  path: string;
  size: number;
  sha256: string;
  width: number;
  height: number;
};
type State = "running" | "cancelling" | "cancelled" | "completed" | "failed" | "uncertain";
type Job = SequenceInput & {
  job_id: string;
  state: State;
  current_frame: number | null;
  completed: Output[];
  error?: string;
};

const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));
const active = (job: Job) => ["running", "cancelling", "uncertain"].includes(job.state);

async function inspectPng(filename: string): Promise<Omit<Output, "frame">> {
  const entry = await lstat(filename);
  if (!entry.isFile() || entry.isSymbolicLink()) throw new Error("Output is not a regular file");
  const bytes = await readFile(filename);
  if (
    bytes.length < 45 ||
    bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a" ||
    bytes.subarray(12, 16).toString("ascii") !== "IHDR" ||
    bytes.subarray(-8, -4).toString("ascii") !== "IEND"
  ) {
    throw new Error("Output is not a complete PNG (signature/IHDR/IEND)");
  }
  let offset = 8;
  let imageData = false;
  let ended = false;
  while (offset + 12 <= bytes.length) {
    const length = bytes.readUInt32BE(offset);
    const end = offset + 12 + length;
    if (end > bytes.length) throw new Error("Truncated PNG chunk");
    const kind = bytes.toString("ascii", offset + 4, offset + 8);
    if (crc32(bytes.subarray(offset + 4, end - 4)) !== bytes.readUInt32BE(end - 4)) {
      throw new Error("PNG chunk CRC mismatch");
    }
    if (kind === "IHDR" && (offset !== 8 || length !== 13)) throw new Error("Invalid PNG header");
    if (kind === "IDAT") imageData = true;
    if (kind === "IEND") {
      if (length !== 0 || end !== bytes.length) throw new Error("Invalid PNG end chunk");
      ended = true;
    }
    offset = end;
  }
  if (!imageData || !ended || offset !== bytes.length) throw new Error("Incomplete PNG chunks");
  const width = bytes.readUInt32BE(16);
  const height = bytes.readUInt32BE(20);
  if (!width || !height) throw new Error("PNG dimensions must be positive");
  return {
    path: filename,
    size: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    width,
    height,
  };
}

/** One bounded queue per MCP process. Cancellation is between frames, never mid-render. */
export class RenderSequences {
  private jobs = new Map<string, Job>();
  private inFlight = new Set<string>();
  private reserving = false;

  constructor(private client: Pick<C4DClient, "request">) {}

  private requireIdle(): void {
    if (this.reserving || this.inFlight.size > 0 || [...this.jobs.values()].some(active)) {
      throw new Error("A sequence is already active or its render outcome is uncertain");
    }
  }

  private find(id: string): Job {
    const job = this.jobs.get(id);
    if (!job) throw new Error("Unknown job_id; jobs belong to this MCP server session");
    return job;
  }

  status(id: string): Job & { settled: boolean } {
    return { ...structuredClone(this.find(id)), settled: !this.inFlight.has(id) };
  }

  private async persist(job: Job): Promise<void> {
    // This directory was created exclusively by start(). Never touch scene files.
    const temporary = path.join(job.output_directory, ".manifest.tmp");
    await writeFile(temporary, JSON.stringify(job, null, 2) + "\n");
    await rename(temporary, path.join(job.output_directory, "manifest.json"));
  }

  async start(input: SequenceInput): Promise<Job> {
    this.requireIdle();
    if (this.jobs.size >= 20)
      throw new Error("Session job limit reached (20); restart the MCP server");
    if (!path.isAbsolute(input.output_directory))
      throw new Error("output_directory must be absolute");
    if (
      !input.document_name.trim() ||
      !input.render_data_name.trim() ||
      input.frames.length < 1 ||
      input.frames.length > 300 ||
      input.frames.some(
        (frame) => !Number.isSafeInteger(frame) || frame < 0 || frame > 1_000_000,
      ) ||
      new Set(input.frames).size !== input.frames.length
    ) {
      throw new Error("Require unique frames (1..300), each in 0..1000000, and non-empty names");
    }
    this.reserving = true;
    try {
      const capabilities = await this.client.request<{ features?: { rs_render_frame?: boolean } }>(
        "get_capabilities",
      );
      if (capabilities.features?.rs_render_frame !== true) {
        throw new Error(
          "Installed bridge lacks explicit-frame rendering; install and restart C4D first",
        );
      }
      const job: Job = {
        ...input,
        // eslint-disable-next-line unicorn/no-array-sort -- ES2022 lib; only sort this private copy.
        frames: [...input.frames].sort((a, b) => a - b),
        output_directory: path.resolve(input.output_directory),
        job_id: randomUUID(),
        state: "running",
        current_frame: null,
        completed: [],
      };
      // No recursive mkdir and no reuse: cannot overwrite an existing directory's files.
      await mkdir(job.output_directory);
      await this.persist(job);
      this.jobs.set(job.job_id, job);
      this.inFlight.add(job.job_id);
      void this.run(job);
      return this.status(job.job_id);
    } finally {
      this.reserving = false;
    }
  }

  cancel(id: string): Job {
    const job = this.find(id);
    if (job.state === "running") job.state = "cancelling";
    // The render loop is the only manifest writer, avoiding out-of-order disk snapshots.
    return this.status(id);
  }

  async resume(id: string): Promise<Job> {
    this.requireIdle();
    const job = this.find(id);
    if (job.state !== "cancelled") {
      throw new Error(
        "Only a cleanly cancelled job can resume; failed/uncertain frames need inspection",
      );
    }
    this.reserving = true;
    job.state = "running";
    this.inFlight.add(id);
    try {
      for (const output of job.completed) {
        const actual = await inspectPng(output.path);
        if (actual.sha256 !== output.sha256)
          throw new Error("Completed output changed; refusing resume");
      }
      await this.persist(job);
      void this.run(job);
      return this.status(id);
    } catch (error) {
      job.state = "failed";
      job.error = errorText(error);
      this.inFlight.delete(id);
      throw error;
    } finally {
      this.reserving = false;
    }
  }

  private async run(job: Job): Promise<void> {
    let awaitingBridge = false;
    try {
      for (const frame of job.frames) {
        if (job.completed.some((entry) => entry.frame === frame)) continue;
        if (this.find(job.job_id).state === "cancelling") {
          job.state = "cancelled";
          break;
        }
        job.current_frame = frame;
        await this.persist(job);
        // Re-check after yielding to disk IO; cancellation must not enqueue another frame.
        if (job.state === "cancelling") {
          job.state = "cancelled";
          break;
        }
        const outputPath = path.join(
          job.output_directory,
          `frame_${String(frame).padStart(6, "0")}.png`,
        );
        awaitingBridge = true;
        const result = await this.client.request<{
          frame: number;
          width: number;
          height: number;
          beauty: { path: string; size: number };
          expected_missing: unknown[];
        }>(
          "rs_render",
          {
            document_name: job.document_name,
            render_data_name: job.render_data_name,
            output_path: outputPath,
            frame,
            sequence_frame: true,
            force: true,
            overwrite: false,
          },
          1_800_000,
        );
        awaitingBridge = false;
        if (
          result.frame !== frame ||
          result.beauty.path !== outputPath ||
          !Array.isArray(result.expected_missing) ||
          result.expected_missing.length > 0
        ) {
          throw new Error("Render result does not match requested frame/output");
        }
        const verified = await inspectPng(outputPath);
        if (
          verified.width !== result.width ||
          verified.height !== result.height ||
          verified.size !== result.beauty.size ||
          (job.completed.length > 0 &&
            (verified.width !== job.completed[0].width ||
              verified.height !== job.completed[0].height))
        ) {
          throw new Error("PNG dimensions/size differ from render result or earlier frames");
        }
        job.completed.push({ frame, ...verified });
        await this.persist(job);
      }
      if (job.completed.length === job.frames.length) job.state = "completed";
    } catch (error) {
      const message = errorText(error);
      // The bridge may still be rendering after loss of transport. Never retry automatically.
      job.state =
        awaitingBridge && (!(error instanceof C4DCommandError) || /timed?\s*out/i.test(message))
          ? "uncertain"
          : "failed";
      job.error = message;
    } finally {
      job.current_frame = null;
      try {
        await this.persist(job);
      } catch (error) {
        if (job.state !== "uncertain") job.state = "failed";
        job.error = `${job.error ?? ""} Manifest write failed: ${errorText(error)}`.trim();
      } finally {
        this.inFlight.delete(job.job_id);
      }
    }
  }
}

const managers = new WeakMap<C4DClient, RenderSequences>();
export function sequencesFor(client: C4DClient): RenderSequences {
  let manager = managers.get(client);
  if (!manager) {
    manager = new RenderSequences(client);
    managers.set(client, manager);
  }
  return manager;
}
