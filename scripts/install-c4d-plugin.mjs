import { cp, lstat, mkdir, readdir, realpath, rename, stat } from "node:fs/promises";
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

function normalizeDriveAbsolute(input, label) {
  if (!/^[A-Za-z]:[\\/]/.test(input) || !path.win32.isAbsolute(input)) {
    throw new Error(`${label} must be a drive-letter absolute Windows path`);
  }
  return path.win32.normalize(input);
}

function samePath(left, right) {
  return path.win32.normalize(left).toLowerCase() === path.win32.normalize(right).toLowerCase();
}

function isSameOrWithin(parent, candidate) {
  const relative = path.win32.relative(parent, candidate);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.win32.sep}`) &&
      relative !== ".." &&
      !path.win32.isAbsolute(relative))
  );
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

async function requireDirectory(input, label) {
  let entry;
  try {
    entry = await stat(input);
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error(`${label} does not exist: ${input}`, { cause: error });
    }
    throw error;
  }
  if (!entry.isDirectory()) {
    throw new Error(`${label} must be a directory: ${input}`);
  }
  return realpath(input);
}

async function resolveExistingAncestor(input) {
  let candidate = input;
  for (;;) {
    try {
      await lstat(candidate);
      const resolvedEntry = await stat(candidate);
      if (!samePath(candidate, input) && !resolvedEntry.isDirectory()) {
        throw new Error(`Destination ancestor must be a directory: ${candidate}`);
      }
      return { path: candidate, realPath: await realpath(candidate) };
    } catch (error) {
      if (error?.code !== "ENOENT") {
        throw error;
      }
      const parent = path.win32.dirname(candidate);
      if (samePath(parent, candidate)) {
        throw new Error(`No existing destination ancestor found for ${input}`, {
          cause: error,
        });
      }
      candidate = parent;
    }
  }
}

function getMaxonRoot(appData) {
  if (!appData) {
    throw new Error("APPDATA is not set; pass --preference <absolute-path>");
  }
  return path.win32.join(normalizeDriveAbsolute(appData, "APPDATA"), "Maxon");
}

async function discoverPreference(appData) {
  const maxonRoot = getMaxonRoot(appData);
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

async function validateInstallPlan(repoRoot, preference, appData) {
  const maxonRoot = getMaxonRoot(appData);
  const plan = buildInstallPlan(repoRoot, preference);
  const normalizedPreference = path.win32.normalize(preference);

  if (!samePath(path.win32.dirname(normalizedPreference), maxonRoot)) {
    throw new Error(`Preference must be a direct child of the current Maxon root: ${maxonRoot}`);
  }

  const realMaxonRoot = await requireDirectory(maxonRoot, "Maxon root");
  const realPreference = await requireDirectory(normalizedPreference, "Preference");
  const realPreferenceName = path.win32.basename(realPreference);
  if (
    !samePath(path.win32.dirname(realPreference), realMaxonRoot) ||
    findC4D2025Preferences(realMaxonRoot, [realPreferenceName]).length !== 1
  ) {
    throw new Error(
      `Preference real path must be a Cinema 4D 2025 direct child of the current Maxon root; reparse escape rejected: ${realPreference}`,
    );
  }

  const realSource = await requireDirectory(plan.source, "Installer source");
  const destinationAncestor = await resolveExistingAncestor(plan.destination);
  const realDestination = path.win32.join(
    destinationAncestor.realPath,
    path.win32.relative(destinationAncestor.path, plan.destination),
  );

  if (!isSameOrWithin(realPreference, realDestination)) {
    throw new Error(`Destination real path escapes the selected preference: ${realDestination}`);
  }
  if (isSameOrWithin(realSource, realDestination) || isSameOrWithin(realDestination, realSource)) {
    throw new Error("Real source and destination paths cannot overlap");
  }

  return plan;
}

async function main() {
  const { install, preference: requestedPreference } = parseArguments(process.argv.slice(2));
  const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
  const preference = requestedPreference ?? (await discoverPreference(process.env.APPDATA));
  const plan = await validateInstallPlan(repoRoot, preference, process.env.APPDATA);

  console.log(`Mode: ${install ? "install" : "dry-run"}`);
  console.log(`Source: ${plan.source}`);
  console.log(`Destination: ${plan.destination}`);

  if (!install) {
    console.log("No files were changed. Pass --install to apply this plan.");
    return;
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
