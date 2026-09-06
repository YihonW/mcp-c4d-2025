import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const SERVER_ENTRY = path.join(REPO_ROOT, "dist", "index.js");

export const TEST_PREFIX = "e2e_";

type ToolCaller = {
  call<T = unknown>(name: string, args?: Record<string, unknown>): Promise<T>;
};

/** Force-close one uniquely named test document; absence is the only ignored case. */
export async function closeDocumentIfPresent(
  client: ToolCaller,
  documentName: string,
): Promise<boolean> {
  const listed = await client.call<{
    documents: Array<{ name: string }>;
  }>("list_documents", {});
  const matches = (listed.documents ?? []).filter((document) => document.name === documentName);
  if (matches.length === 0) return false;
  if (matches.length > 1) {
    throw new Error(
      `refusing to close ${matches.length} documents named ${JSON.stringify(documentName)}`,
    );
  }
  await client.call("close_document", { name: documentName, force: true });
  return true;
}

type BridgeProbeDecision = {
  ready: boolean;
  reason?: string;
};

type BridgeCapabilities = {
  c4d_version: number;
  display_version: string;
  compatibility: string;
  platform: string;
  bridge_version: string;
  security: {
    loopback: boolean;
    token_required: boolean;
    exec_python: boolean;
  };
};

type LiveSecurityExpectation = {
  tokenRequired: boolean;
  execPython: boolean;
};

type RequiredRedshiftCapabilities = {
  renderer: { supported: true; id: 1036219 };
  module: { supported: true };
  node_space: {
    supported: true;
    id: "com.redshift3d.redshift4c4d.class.nodespace";
    node_template_count: number;
  };
  aov_api: { supported: true; aliases: Record<string, number> };
  materials: { supported: true };
  lights: {
    supported: true;
    types: { area: { supported: true }; dome: { supported: true } };
  };
  camera: { supported: true };
  render: { supported: true };
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};

/** Fail-fast policy used by the non-skippable Cinema 4D Redshift smoke command. */
export function requireRedshiftCapabilities(
  capabilities: unknown,
): asserts capabilities is RequiredRedshiftCapabilities {
  const root = asRecord(capabilities);
  const renderer = asRecord(root.renderer);
  if (renderer.supported !== true || renderer.id !== 1036219) {
    throw new Error("Redshift renderer 1036219 must be supported");
  }
  if (asRecord(root.module).supported !== true) {
    throw new Error("Redshift module must be supported");
  }
  const nodeSpace = asRecord(root.node_space);
  if (
    nodeSpace.supported !== true ||
    nodeSpace.id !== "com.redshift3d.redshift4c4d.class.nodespace"
  ) {
    throw new Error("Redshift node_space identity must match the verified Redshift node space");
  }
  if (
    typeof nodeSpace.node_template_count !== "number" ||
    !Number.isInteger(nodeSpace.node_template_count) ||
    nodeSpace.node_template_count <= 0
  ) {
    throw new Error("Redshift node_template_count must be a positive integer");
  }
  const aovApi = asRecord(root.aov_api);
  if (aovApi.supported !== true) {
    throw new Error("Redshift AOV API must include mutation support");
  }
  const aliases = asRecord(aovApi.aliases);
  if (Object.keys(aliases).length === 0) {
    throw new Error("Redshift AOV alias map must not be empty");
  }
  if (asRecord(root.materials).supported !== true) {
    throw new Error("Redshift materials must be supported");
  }
  const lights = asRecord(root.lights);
  if (lights.supported !== true) {
    throw new Error("Redshift lights must be supported");
  }
  const lightTypes = asRecord(lights.types);
  for (const type of ["area", "dome"] as const) {
    if (asRecord(lightTypes[type]).supported !== true) {
      throw new Error(`Redshift ${type} light must be supported`);
    }
  }
  if (asRecord(root.camera).supported !== true) {
    throw new Error("Redshift camera must be supported");
  }
  if (asRecord(root.render).supported !== true) {
    throw new Error("Redshift render must be supported");
  }
}

/** Fail-fast policy used by the non-skippable Cinema 4D 2025 smoke command. */
export function requireLiveBridge(
  probe: BridgeProbeDecision,
  capabilities?: BridgeCapabilities,
  expectedSecurity: LiveSecurityExpectation = { tokenRequired: false, execPython: false },
): void {
  if (!probe.ready) {
    const detail = probe.reason ? `: ${probe.reason}` : "";
    throw new Error(`Cinema 4D bridge not reachable${detail}`);
  }

  const rawVersion = capabilities?.c4d_version;
  const release =
    typeof rawVersion === "number" && Number.isInteger(rawVersion)
      ? Math.floor(rawVersion / 1000)
      : undefined;
  if (release !== 2025) {
    throw new Error(`Cinema 4D 2025 required; bridge reports release ${release ?? "unknown"}`);
  }
  if (rawVersion !== 2025302) {
    throw new Error(`Cinema 4D 2025.3.2 required; bridge reports raw version ${rawVersion}`);
  }
  if (capabilities?.display_version !== "2025.3.2") {
    throw new Error(
      `display_version must be 2025.3.2; bridge reports ${capabilities?.display_version ?? "missing"}`,
    );
  }
  if (capabilities.compatibility !== "supported") {
    throw new Error(
      `compatibility must be supported; bridge reports ${capabilities.compatibility ?? "missing"}`,
    );
  }
  if (capabilities.platform !== "win32") {
    throw new Error(
      `Windows platform win32 required; bridge reports ${capabilities.platform ?? "missing"}`,
    );
  }
  if (capabilities.bridge_version !== "0.5.0") {
    throw new Error(
      `bridge 0.5.0 required; bridge reports ${capabilities.bridge_version ?? "missing"}`,
    );
  }
  if (capabilities.security?.loopback !== true) {
    throw new Error("security.loopback must be true for the foundation live gate");
  }
  if (capabilities.security.token_required !== expectedSecurity.tokenRequired) {
    throw new Error(
      `security.token_required must be ${expectedSecurity.tokenRequired}; bridge reports ${capabilities.security.token_required}`,
    );
  }
  if (capabilities.security.exec_python !== expectedSecurity.execPython) {
    throw new Error(
      `security.exec_python must be ${expectedSecurity.execPython}; bridge reports ${capabilities.security.exec_python}`,
    );
  }
}

function ensureBuilt(): void {
  if (existsSync(SERVER_ENTRY)) return;
  const r = spawnSync("npm", ["run", "build"], { cwd: REPO_ROOT, stdio: "inherit", shell: true });
  if (r.status !== 0) {
    throw new Error("failed to build MCP server before tests");
  }
}

/** Thin MCP client wrapper that returns JSON-parsed tool results. */
export class MCPTestClient {
  private client: Client;
  private transport: StdioClientTransport | null = null;

  constructor() {
    this.client = new Client({ name: "mcp-cinema4d-e2e", version: "0.0.1" }, { capabilities: {} });
  }

  async connect(): Promise<void> {
    ensureBuilt();
    this.transport = new StdioClientTransport({
      command: process.execPath, // current Node binary
      args: [SERVER_ENTRY],
      // Let the bridge host/port flow through from the shell env.
      env: { ...process.env } as Record<string, string>,
    });
    await this.client.connect(this.transport);
  }

  async close(): Promise<void> {
    try {
      await this.client.close();
    } catch {
      /* ignore */
    }
    this.transport = null;
  }

  async call<T = unknown>(
    name: string,
    args: Record<string, unknown> = {},
    options: { timeoutMs?: number } = {},
  ): Promise<T> {
    const res = await this.client.callTool(
      { name, arguments: args },
      undefined,
      options.timeoutMs !== undefined ? { timeout: options.timeoutMs } : undefined,
    );
    const text = extractText(res);
    if (res.isError) {
      throw new Error(`tool ${name} returned error: ${text}`);
    }
    if (!text) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch (err) {
      throw new Error(`tool ${name} returned non-JSON text: ${text}`, { cause: err });
    }
  }

  /** Like call() but returns the raw error message instead of throwing. */
  async callExpectError(name: string, args: Record<string, unknown> = {}): Promise<string> {
    const res = await this.client.callTool({ name, arguments: args });
    if (!res.isError) {
      throw new Error(`expected tool ${name} to error, got ok: ${extractText(res)}`);
    }
    return extractText(res);
  }

  /**
   * Returns the unwrapped MCP content array — used by tests that need to
   * inspect non-text parts (e.g. ``preview_render`` returns ``[image, text]``
   * and ``call()``'s text extractor would just see the image part).
   */
  async callRaw(
    name: string,
    args: Record<string, unknown> = {},
    options: { timeoutMs?: number } = {},
  ): Promise<{ content: Array<Record<string, unknown>> }> {
    const res = await this.client.callTool(
      { name, arguments: args },
      undefined,
      options.timeoutMs !== undefined ? { timeout: options.timeoutMs } : undefined,
    );
    if (res.isError) {
      throw new Error(`tool ${name} returned error: ${extractText(res)}`);
    }
    const content = Array.isArray(res?.content)
      ? (res.content as Array<Record<string, unknown>>)
      : [];
    return { content };
  }
}

function extractText(res: any): string {
  const content = res?.content;
  if (!Array.isArray(content) || content.length === 0) return "";
  const first = content[0];
  return typeof first?.text === "string" ? first.text : "";
}

/** Connect, ping the bridge. Returns true if C4D + plugin are reachable. */
export async function probeBridge(suite: string): Promise<{
  ready: boolean;
  reason?: string;
  client?: MCPTestClient;
}> {
  const strictLive = process.env.C4D_MCP_REQUIRE_LIVE === "1";
  const allowLive = strictLive || process.env.C4D_MCP_ALLOW_LIVE_E2E === "1";
  if (!allowLive) {
    const reason =
      "explicit live opt-in required (C4D_MCP_ALLOW_LIVE_E2E=1 or C4D_MCP_REQUIRE_LIVE=1)";
    printSkipBanner(suite, reason, "Live Cinema 4D E2E is disabled by default");
    return { ready: false, reason };
  }
  const client = new MCPTestClient();
  try {
    await client.connect();
    const pong = await client.call<{ pong: boolean }>("ping", {});
    if (!pong?.pong) {
      const unavailable = { ready: false, reason: "ping returned unexpected payload" } as const;
      if (strictLive) throw new Error(unavailable.reason);
      await client.close();
      printSkipBanner(suite, unavailable.reason);
      return unavailable;
    }
    return { ready: true, client };
  } catch (err) {
    await client.close();
    const reason = err instanceof Error ? err.message : String(err);
    if (strictLive) requireLiveBridge({ ready: false, reason });
    printSkipBanner(suite, reason);
    return { ready: false, reason };
  }
}

export function printSkipBanner(
  suite: string,
  reason: string,
  summary = "Cinema 4D bridge not reachable",
): void {
  const host = process.env.C4D_MCP_HOST ?? process.env.C4D_BRIDGE_HOST ?? "127.0.0.1";
  const port = process.env.C4D_MCP_PORT ?? process.env.C4D_BRIDGE_PORT ?? "18710";
  // Visible banner so skips are not confused with success.
  const divider = "─".repeat(72);
  console.warn(
    [
      divider,
      `[e2e ${suite}] SKIPPING — ${summary}`,
      ` reason : ${reason}`,
      ` target : ${host}:${port}`,
      " ",
      " To run the guarded foundation live test:",
      "   npm run test:live:2025",
      " ",
      " Other E2E suites require C4D_MCP_ALLOW_LIVE_E2E=1 explicitly.",
      divider,
    ].join("\n"),
  );
}

/**
 * Reset for tests: swap in a fresh empty BaseDocument via `new_document`.
 *
 * Why a full document swap instead of prefix-scoped cleanup? C4D 2026
 * occasionally stalls its CoreMessage pump after a mix of set_mesh +
 * obj.Remove() operations on the same doc — the bridge's command queue
 * drains, then the main thread never processes the next SpecialEventAdd.
 * Swapping the active document sidesteps that entirely: no per-object
 * Remove loop is needed, and the previous doc's undo buffer is gone
 * along with it.
 *
 * `new_document` is a boring, well-tested call on the bridge. If it
 * fails (really old bridge), we fall back to exec_python and then to
 * prefix cleanup.
 */
export async function resetScene(client: MCPTestClient): Promise<boolean> {
  try {
    await client.call("new_document", { make_active: true });
    return true;
  } catch {
    /* fall through to exec_python */
  }
  try {
    await client.call("exec_python", {
      code: `
import c4d
from c4d import documents
doc = documents.GetActiveDocument()
if doc is not None:
    obj = doc.GetFirstObject()
    while obj is not None:
        nxt = obj.GetNext()
        obj.Remove()
        obj = nxt
    mat = doc.GetFirstMaterial()
    while mat is not None:
        nxt = mat.GetNext()
        mat.Remove()
        mat = nxt
    active_rd = doc.GetActiveRenderData()
    rd = doc.GetFirstRenderData()
    while rd is not None:
        nxt = rd.GetNext()
        if rd is not active_rd:
            rd.Remove()
        rd = nxt
    td = doc.GetTakeData()
    if td is not None:
        def _drop_children(parent):
            c = parent.GetDown()
            while c is not None:
                nxt = c.GetNext()
                _drop_children(c)
                td.DeleteTake(c)
                c = nxt
        _drop_children(td.GetMainTake())
        td.SetCurrentTake(td.GetMainTake())
    c4d.EventAdd()
result = {"ok": True}
`.trim(),
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Remove every test-prefixed entity we know how to address. Safe fallback
 * when `exec_python` is disabled. Objects, materials, render data (except
 * the active one — removing that would invalidate the doc), layers,
 * non-main takes.
 *
 * Sequential on purpose: Cinema 4D dispatches on a single main thread, so
 * parallel removes would queue up on the bridge and risk racing each
 * other's handle resolution.
 */
export async function cleanupByPrefix(client: MCPTestClient): Promise<void> {
  const pattern = `^${TEST_PREFIX}`;

  async function cleanupObjects(): Promise<void> {
    try {
      const listed = await client.call<{ entities: Array<{ name: string; path: string }> }>(
        "list_entities",
        { kind: "object", name_pattern: pattern },
      );
      for (const e of listed.entities ?? []) {
        await client.call("remove_entity", {
          handle: { kind: "object", path: e.path ?? undefined, name: e.name },
        });
      }
    } catch {
      /* best-effort */
    }
  }

  async function cleanupMaterials(): Promise<void> {
    try {
      const listed = await client.call<{ entities: Array<{ name: string }> }>("list_entities", {
        kind: "material",
        name_pattern: pattern,
      });
      for (const e of listed.entities ?? []) {
        await client.call("remove_entity", { handle: { kind: "material", name: e.name } });
      }
    } catch {
      /* best-effort */
    }
  }

  async function cleanupRenderData(): Promise<void> {
    try {
      const listed = await client.call<{
        entities: Array<{ name: string; is_active?: boolean }>;
      }>("list_entities", { kind: "render_data", name_pattern: pattern });
      for (const e of listed.entities ?? []) {
        if (e.is_active) continue; // dropping the active RD invalidates the doc
        await client.call("remove_entity", { handle: { kind: "render_data", name: e.name } });
      }
    } catch {
      /* best-effort */
    }
  }

  await cleanupObjects();
  await cleanupMaterials();
  await cleanupRenderData();
}

export function testName(base: string): string {
  return `${TEST_PREFIX}${base}`;
}
