import { cp, lstat, mkdir, readdir, rename, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildInstallPlan, findC4D2025Preferences } from "../src/install/c4d-install.ts";

function parseArguments(args) {
  let install = false;
  let dryRun = false;
  let preference;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--install") {
      install = true;
    } else if (argument === "--dry-run") {
      dryRun = true;
    } else if (argument === "--preference") {
      preference = args[index + 1];
      if (!preference || preference.startsWith("--")) {
        throw new Error("--preference requires an absolute path");
      }
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${argument}`);
    }
  }

  if (install && dryRun) {
    throw new Error("Choose either --install or --dry-run, not both");
  }

  return { install, preference };
}

async function pathExists(input) {
  try {
    await lstat(input);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

async function discoverPreference(appData) {
  if (!appData) {
    throw new Error("APPDATA is not set; pass --preference <absolute-path>");
  }

  const maxonRoot = path.win32.join(appData, "Maxon");
  let entries;
  try {
    entries = await readdir(maxonRoot, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error(
        `No Maxon preferences found at ${maxonRoot}; pass --preference <absolute-path>`,
        { cause: error },
      );
    }
    throw error;
  }

  const matches = findC4D2025Preferences(
    maxonRoot,
    entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name),
  );
  if (matches.length === 0) {
    throw new Error(
      `No Cinema 4D 2025 preference found at ${maxonRoot}; pass --preference <absolute-path>`,
    );
  }
  if (matches.length > 1) {
    throw new Error(
      "Multiple Cinema 4D 2025 preferences found; choose one with --preference <absolute-path>",
    );
  }
  return matches[0];
}

async function main() {
  const { install, preference: requestedPreference } = parseArguments(process.argv.slice(2));
  const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
  const preference = requestedPreference ?? (await discoverPreference(process.env.APPDATA));
  const plan = buildInstallPlan(repoRoot, preference);

  console.log(`Mode: ${install ? "install" : "dry-run"}`);
  console.log(`Source: ${plan.source}`);
  console.log(`Destination: ${plan.destination}`);

  if (!install) {
    console.log("No files were changed. Pass --install to apply this plan.");
    return;
  }

  const sourceStats = await stat(plan.source);
  if (!sourceStats.isDirectory()) {
    throw new Error(`Installer source is not a directory: ${plan.source}`);
  }

  await mkdir(path.win32.dirname(plan.destination), { recursive: true });
  if (await pathExists(plan.destination)) {
    const timestamp = new Date().toISOString().replaceAll(":", "-");
    const backup = `${plan.destination}.backup-${timestamp}`;
    await rename(plan.destination, backup);
    console.log(`Backup: ${backup}`);
  }
  await cp(plan.source, plan.destination, {
    recursive: true,
    force: false,
    errorOnExist: true,
  });
  console.log("Cinema 4D bridge installed.");
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
