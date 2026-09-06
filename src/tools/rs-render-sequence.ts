import { z } from "zod";
import { sequencesFor } from "../render-sequence.js";
import { defineTool, textResult } from "./define-tool.js";

export const rsRenderSequenceTool = defineTool({
  name: "rs_render_sequence",
  group: "redshift",
  title: "Start Redshift PNG Sequence",
  description:
    "Start a bounded background Beauty-only PNG sequence (1..300 unique frames), returning job_id immediately. Requires an updated bridge, a uniquely named open document/RenderData with PNG format and no enabled AOVs, and a new output directory whose parent exists. Never overwrites. Do not edit the scene during rendering. Use rs_sequence_status and rs_sequence_control on this same MCP server. Manifest and SHA-256 checks persist beside the frames; job control does not survive server restart.",
  inputShape: {
    document_name: z.string().trim().min(1),
    render_data_name: z.string().trim().min(1),
    output_directory: z.string().min(1),
    frames: z.array(z.number().int().min(0).max(1_000_000)).min(1).max(300),
    force: z.literal(true),
  },
  async handler(args, client) {
    if (args.force !== true) throw new Error("force must be true");
    return textResult(await sequencesFor(client).start(args));
  },
});

export const rsSequenceStatusTool = defineTool({
  name: "rs_sequence_status",
  group: "redshift",
  title: "Read Redshift Sequence Progress",
  description:
    "Read this MCP session's sequence state, current frame, verified completed outputs, and any error without querying or modifying C4D. An uncertain state means a timed-out render may still be running; do not retry it automatically.",
  inputShape: { job_id: z.string().uuid() },
  async handler(args, client) {
    return textResult(sequencesFor(client).status(args.job_id));
  },
});

export const rsSequenceControlTool = defineTool({
  name: "rs_sequence_control",
  group: "redshift",
  title: "Cancel or Resume Redshift Sequence",
  description:
    "Cancel stops scheduling after the in-flight frame finishes; it does not abort a C4D render. Resume is allowed only after clean cancellation in this same MCP session, verifies completed-file hashes, and never overwrites. Do not resume after modifying the scene. Failed or uncertain jobs require inspection; their output files remain intact.",
  inputShape: { job_id: z.string().uuid(), action: z.enum(["cancel", "resume"]) },
  async handler(args, client) {
    const manager = sequencesFor(client);
    return textResult(
      args.action === "cancel" ? manager.cancel(args.job_id) : await manager.resume(args.job_id),
    );
  },
});
