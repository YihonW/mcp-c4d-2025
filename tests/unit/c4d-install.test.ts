import { spawnSync } from "node:child_process";
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { buildInstallPlan, findC4D2025Preferences } from "../../src/install/c4d-install.js";

type InstallerSandbox = {
  root: string;
  repo: string;
  appData: string;
  maxonRoot: string;
  preference: string;
  source: string;
  destination: string;
  script: string;
};

function createInstallerSandbox(): InstallerSandbox {
  const root = mkdtempSync(path.join(tmpdir(), "c4d-installer-"));
  const repo = path.join(root, "repo");
  const appData = path.join(root, "AppData", "Roaming");
  const maxonRoot = path.join(appData, "Maxon");
  const preference = path.join(maxonRoot, "Maxon Cinema 4D 2025_abcd");
  const source = path.join(repo, "plugin", "cinema4d_mcp_bridge");
  const destination = path.join(preference, "plugins", "cinema4d_mcp_bridge");
  const script = path.join(repo, "scripts", "install-c4d-plugin.mjs");

  mkdirSync(path.dirname(script), { recursive: true });
  mkdirSync(path.join(repo, "src", "install"), { recursive: true });
  mkdirSync(source, { recursive: true });
  mkdirSync(preference, { recursive: true });
  cpSync(path.resolve("scripts/install-c4d-plugin.mjs"), script);
  cpSync(
    path.resolve("src/install/c4d-install.ts"),
    path.join(repo, "src", "install", "c4d-install.ts"),
  );
  writeFileSync(path.join(source, "new.txt"), "new bridge content", "utf8");

  return { root, repo, appData, maxonRoot, preference, source, destination, script };
}

function runInstaller(sandbox: InstallerSandbox, args: string[] = []) {
  return spawnSync(process.execPath, [sandbox.script, ...args], {
    cwd: sandbox.repo,
    encoding: "utf8",
    env: { ...process.env, APPDATA: sandbox.appData },
  });
}

function snapshotTree(root: string): string[] {
  const snapshot: string[] = [];

  function visit(directory: string) {
    for (const name of readdirSync(directory).toSorted()) {
      const fullPath = path.join(directory, name);
      const relativePath = path.relative(root, fullPath).replaceAll("\\", "/");
      const entry = lstatSync(fullPath);
      if (entry.isSymbolicLink()) {
        snapshot.push(`link:${relativePath}->${readlinkSync(fullPath)}`);
      } else if (entry.isDirectory()) {
        snapshot.push(`dir:${relativePath}`);
        visit(fullPath);
      } else {
        snapshot.push(`file:${relativePath}:${readFileSync(fullPath).toString("base64")}`);
      }
    }
  }

  visit(root);
  return snapshot;
}

describe("findC4D2025Preferences", () => {
  test("selects only Cinema 4D 2025 preference folders", () => {
    expect(
      findC4D2025Preferences("C:/Users/Test/AppData/Roaming/Maxon", [
        "Maxon Cinema 4D 2024_abcd",
        "Maxon Cinema 4D 2025_1234",
        "Maxon Cinema 4D 2026_efgh",
      ]),
    ).toEqual(["C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234"]);
  });

  test("rejects a relative Maxon application-data path", () => {
    expect(() =>
      findC4D2025Preferences("AppData/Roaming/Maxon", ["Maxon Cinema 4D 2025_1234"]),
    ).toThrow(/absolute/i);
  });

  test.each([
    "\\Users\\Test\\AppData\\Roaming\\Maxon",
    "/Users/Test/AppData/Roaming/Maxon",
    "\\\\server\\share\\Maxon",
    "\\\\?\\C:\\Users\\Test\\Maxon",
  ])("rejects non-drive-local Maxon application-data path %s", (appData) => {
    expect(() => findC4D2025Preferences(appData, ["Maxon Cinema 4D 2025_1234"])).toThrow(
      /drive.*absolute/i,
    );
  });

  test("ignores matching-looking entries that escape the Maxon folder", () => {
    expect(
      findC4D2025Preferences("C:/Users/Test/AppData/Roaming/Maxon", [
        "../Maxon Cinema 4D 2025_1234",
        "C:/Elsewhere/Maxon Cinema 4D 2025_5678",
      ]),
    ).toEqual([]);
  });
});

describe("buildInstallPlan", () => {
  test("points from the repository bridge to the selected preference plugins folder", () => {
    expect(
      buildInstallPlan(
        "C:/work/mcp_c4d",
        "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234",
      ),
    ).toEqual({
      source: "C:/work/mcp_c4d/plugin/cinema4d_mcp_bridge",
      destination:
        "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234/plugins/cinema4d_mcp_bridge",
    });
  });

  test.each([
    ["repository", "work/mcp_c4d", "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234"],
    ["preference", "C:/work/mcp_c4d", "Maxon Cinema 4D 2025_1234"],
  ])("rejects a relative %s path", (_label, repoRoot, preferenceRoot) => {
    expect(() => buildInstallPlan(repoRoot, preferenceRoot)).toThrow(/absolute/i);
  });

  test.each([
    "\\work\\mcp_c4d",
    "/work/mcp_c4d",
    "\\\\server\\share\\mcp_c4d",
    "\\\\?\\C:\\work\\mcp_c4d",
    "\\\\.\\C:\\work\\mcp_c4d",
  ])("rejects non-drive-local repository path %s", (repoRoot) => {
    expect(() =>
      buildInstallPlan(repoRoot, "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234"),
    ).toThrow(/drive.*absolute/i);
  });

  test("rejects a preference folder for a release other than 2025", () => {
    expect(() =>
      buildInstallPlan(
        "C:/work/mcp_c4d",
        "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2026_abcd",
      ),
    ).toThrow(/2025/);
  });

  test("rejects a repository root inside the planned destination", () => {
    const preference = "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234";

    expect(() =>
      buildInstallPlan(`${preference}/plugins/cinema4d_mcp_bridge/repository`, preference),
    ).toThrow(/overlap/i);
  });

  test("rejects nested repository and preference roots", () => {
    const preference = "C:/Users/Test/AppData/Roaming/Maxon/Maxon Cinema 4D 2025_1234";

    expect(() => buildInstallPlan(`${preference}/repository`, preference)).toThrow(/overlap/i);
  });

  test("rejects using the repository root as the preference root", () => {
    const sharedRoot = "C:/work/Maxon Cinema 4D 2025_abcd";

    expect(() => buildInstallPlan(sharedRoot, sharedRoot)).toThrow(/same/i);
  });
});

describe("install-c4d-plugin CLI", () => {
  test("defaults to dry-run without changing any entry in the temporary tree", () => {
    const sandbox = createInstallerSandbox();
    const before = snapshotTree(sandbox.root);

    try {
      const result = runInstaller(sandbox);

      expect(result.status).toBe(0);
      expect(result.stdout).toContain("Mode: dry-run");
      expect(result.stdout).toContain("Source:");
      expect(result.stdout).toContain("Destination:");
      expect(snapshotTree(sandbox.root)).toEqual(before);
      expect(existsSync(path.join(sandbox.preference, "plugins"))).toBe(false);
      expect(readdirSync(sandbox.maxonRoot).some((name) => name.includes(".backup-"))).toBe(false);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("refuses multiple discovered preferences without an explicit preference", () => {
    const sandbox = createInstallerSandbox();
    mkdirSync(path.join(sandbox.maxonRoot, "Maxon Cinema 4D 2025_efgh"), {
      recursive: true,
    });

    try {
      const result = runInstaller(sandbox, ["--dry-run"]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/multiple.*--preference/i);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects a nonexistent explicit preference without changing the tree", () => {
    const sandbox = createInstallerSandbox();
    rmSync(sandbox.preference, { recursive: true });
    const before = snapshotTree(sandbox.root);

    try {
      const result = runInstaller(sandbox, ["--dry-run", "--preference", sandbox.preference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/preference.*exist|directory/i);
      expect(snapshotTree(sandbox.root)).toEqual(before);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects an explicit preference outside the current Maxon root", () => {
    const sandbox = createInstallerSandbox();
    const outsidePreference = path.join(sandbox.root, "outside", "Maxon Cinema 4D 2025_outside");
    mkdirSync(outsidePreference, { recursive: true });
    const before = snapshotTree(sandbox.root);

    try {
      const result = runInstaller(sandbox, ["--dry-run", "--preference", outsidePreference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/direct child.*Maxon/i);
      expect(snapshotTree(sandbox.root)).toEqual(before);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects a file used as an explicit preference", () => {
    const sandbox = createInstallerSandbox();
    rmSync(sandbox.preference, { recursive: true });
    writeFileSync(sandbox.preference, "not a directory", "utf8");

    try {
      const result = runInstaller(sandbox, ["--dry-run", "--preference", sandbox.preference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/preference.*directory/i);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects a nested explicit preference", () => {
    const sandbox = createInstallerSandbox();
    const nestedPreference = path.join(sandbox.maxonRoot, "nested", "Maxon Cinema 4D 2025_nested");
    mkdirSync(nestedPreference, { recursive: true });

    try {
      const result = runInstaller(sandbox, ["--dry-run", "--preference", nestedPreference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/direct child.*Maxon/i);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects a preference junction that escapes the Maxon root", () => {
    const sandbox = createInstallerSandbox();
    const outside = path.join(sandbox.root, "outside-preference");
    rmSync(sandbox.preference, { recursive: true });
    mkdirSync(outside);
    symlinkSync(outside, sandbox.preference, "junction");
    const before = snapshotTree(sandbox.root);

    try {
      const result = runInstaller(sandbox, ["--dry-run", "--preference", sandbox.preference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/real path.*Maxon|escape/i);
      expect(snapshotTree(sandbox.root)).toEqual(before);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects a real source path that overlaps the destination", () => {
    const sandbox = createInstallerSandbox();
    rmSync(sandbox.source, { recursive: true });
    symlinkSync(sandbox.preference, sandbox.source, "junction");

    try {
      const result = runInstaller(sandbox, ["--dry-run", "--preference", sandbox.preference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/real source.*destination.*overlap/i);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("backs up the complete old target before copying the new bridge", () => {
    const sandbox = createInstallerSandbox();
    mkdirSync(path.join(sandbox.destination, "nested"), { recursive: true });
    writeFileSync(path.join(sandbox.destination, "old.txt"), "old bridge content", "utf8");
    writeFileSync(path.join(sandbox.destination, "nested", "state.txt"), "old state", "utf8");
    const oldTree = snapshotTree(sandbox.destination);
    const sourceTree = snapshotTree(sandbox.source);

    try {
      const result = runInstaller(sandbox, ["--install", "--preference", sandbox.preference]);
      const pluginRoot = path.dirname(sandbox.destination);
      const backupNames = readdirSync(pluginRoot).filter((name) =>
        name.startsWith("cinema4d_mcp_bridge.backup-"),
      );

      expect(result.status).toBe(0);
      expect(backupNames).toHaveLength(1);
      expect(snapshotTree(path.join(pluginRoot, backupNames[0]))).toEqual(oldTree);
      expect(snapshotTree(sandbox.destination)).toEqual(sourceTree);
      expect(existsSync(path.join(sandbox.destination, "old.txt"))).toBe(false);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });

  test("rejects a plugins junction escape before any filesystem write", () => {
    const sandbox = createInstallerSandbox();
    const outside = path.join(sandbox.root, "outside-plugins");
    mkdirSync(outside);
    symlinkSync(outside, path.join(sandbox.preference, "plugins"), "junction");
    const before = snapshotTree(sandbox.root);

    try {
      const result = runInstaller(sandbox, ["--install", "--preference", sandbox.preference]);

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/destination.*escape|real path/i);
      expect(snapshotTree(sandbox.root)).toEqual(before);
    } finally {
      rmSync(sandbox.root, { recursive: true, force: true });
    }
  });
});
