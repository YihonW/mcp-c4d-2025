import path from "node:path";

const C4D_2025_PREFERENCE = /^Maxon Cinema 4D 2025_[^\\/]+$/;

function normalizeAbsolute(input: string, label: string): string {
  if (!path.win32.isAbsolute(input)) {
    throw new Error(`${label} must be an absolute Windows path`);
  }

  return path.win32.normalize(input);
}

function toPortablePath(input: string): string {
  return input.replaceAll("\\", "/");
}

function isSameOrWithin(parent: string, candidate: string): boolean {
  const relative = path.win32.relative(parent, candidate);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.win32.sep}`) &&
      relative !== ".." &&
      !path.win32.isAbsolute(relative))
  );
}

export function findC4D2025Preferences(appData: string, entries: string[]): string[] {
  const maxonRoot = normalizeAbsolute(appData, "Maxon application-data path");

  return entries
    .filter((entry) => C4D_2025_PREFERENCE.test(entry))
    .map((entry) => toPortablePath(path.win32.join(maxonRoot, entry)));
}

export function buildInstallPlan(
  repoRoot: string,
  preferenceRoot: string,
): { source: string; destination: string } {
  const normalizedRepo = normalizeAbsolute(repoRoot, "Repository root");
  const normalizedPreference = normalizeAbsolute(preferenceRoot, "Preference root");

  if (!C4D_2025_PREFERENCE.test(path.win32.basename(normalizedPreference))) {
    throw new Error("Preference root must be a Cinema 4D 2025 preference folder");
  }
  if (normalizedRepo.toLowerCase() === normalizedPreference.toLowerCase()) {
    throw new Error("Repository root and preference root cannot be the same path");
  }
  if (
    isSameOrWithin(normalizedRepo, normalizedPreference) ||
    isSameOrWithin(normalizedPreference, normalizedRepo)
  ) {
    throw new Error("Repository root and preference root cannot overlap");
  }

  const source = path.win32.join(normalizedRepo, "plugin", "cinema4d_mcp_bridge");
  const destination = path.win32.join(normalizedPreference, "plugins", "cinema4d_mcp_bridge");

  if (isSameOrWithin(source, destination) || isSameOrWithin(destination, source)) {
    throw new Error("Installer source and destination paths cannot overlap");
  }

  return {
    source: toPortablePath(source),
    destination: toPortablePath(destination),
  };
}
