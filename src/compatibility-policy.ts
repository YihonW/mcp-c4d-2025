export function classifyC4DVersion(raw: number): {
  release: number;
  status: "supported" | "unverified" | "unsupported";
  display: string;
} {
  if (!Number.isInteger(raw) || raw <= 0) {
    return { release: 0, status: "unsupported", display: "unknown" };
  }

  const release = Math.floor(raw / 1000);
  const minor = Math.floor((raw % 1000) / 100);
  const patch = raw % 100;
  const display = `${release}.${minor}.${patch}`;

  if (release === 2025) {
    return { release, status: "supported", display };
  }
  if (release === 2024 || release === 2026) {
    return { release, status: "unverified", display };
  }
  return { release, status: "unsupported", display };
}
