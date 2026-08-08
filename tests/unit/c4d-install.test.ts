import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { buildInstallPlan, findC4D2025Preferences } from "../../src/install/c4d-install.js";

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
  test("defaults to dry-run and does not create the destination", () => {
    const appData = mkdtempSync(path.join(tmpdir(), "c4d-installer-"));
    const preference = path.join(appData, "Maxon", "Maxon Cinema 4D 2025_abcd");
    mkdirSync(preference, { recursive: true });
    const destination = path.join(preference, "plugins", "cinema4d_mcp_bridge");

    try {
      const output = execFileSync(
        process.execPath,
        [path.resolve("scripts/install-c4d-plugin.mjs")],
        {
          cwd: path.resolve("."),
          encoding: "utf8",
          env: { ...process.env, APPDATA: appData },
        },
      );

      expect(output).toContain("Mode: dry-run");
      expect(output).toContain("Source:");
      expect(output).toContain("Destination:");
      expect(existsSync(destination)).toBe(false);
    } finally {
      rmSync(appData, { recursive: true, force: true });
    }
  });

  test("refuses multiple discovered preferences without an explicit preference", () => {
    const appData = mkdtempSync(path.join(tmpdir(), "c4d-installer-"));
    const maxonRoot = path.join(appData, "Maxon");
    mkdirSync(path.join(maxonRoot, "Maxon Cinema 4D 2025_abcd"), {
      recursive: true,
    });
    mkdirSync(path.join(maxonRoot, "Maxon Cinema 4D 2025_efgh"), {
      recursive: true,
    });

    try {
      const result = spawnSync(
        process.execPath,
        [path.resolve("scripts/install-c4d-plugin.mjs"), "--dry-run"],
        {
          cwd: path.resolve("."),
          encoding: "utf8",
          env: { ...process.env, APPDATA: appData },
        },
      );

      expect(result.status).not.toBe(0);
      expect(result.stderr).toMatch(/multiple.*--preference/i);
    } finally {
      rmSync(appData, { recursive: true, force: true });
    }
  });
});
