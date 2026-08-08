import { describe, expect, test } from "vitest";

import { requireLiveBridge } from "../e2e/harness.js";

describe("requireLiveBridge", () => {
  test("rejects an unreachable bridge in strict live mode", () => {
    expect(() =>
      requireLiveBridge({ ready: false, reason: "connect ECONNREFUSED 127.0.0.1:18710" }),
    ).toThrow(/Cinema 4D bridge not reachable/);
  });

  test("rejects a reachable bridge that is not Cinema 4D 2025", () => {
    expect(() => requireLiveBridge({ ready: true }, { c4d_version: 2026100 })).toThrow(
      /Cinema 4D 2025 required.*2026/i,
    );
  });

  test("accepts a reachable Cinema 4D 2025 bridge", () => {
    expect(() => requireLiveBridge({ ready: true }, { c4d_version: 2025100 })).not.toThrow();
  });
});
