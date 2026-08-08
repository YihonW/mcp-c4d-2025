import { describe, expect, test } from "vitest";

import { requireLiveBridge } from "../e2e/harness.js";

const validCapabilities = {
  c4d_version: 2025302,
  display_version: "2025.3.2",
  compatibility: "supported",
  platform: "win32",
  bridge_version: "0.4.0",
  security: { loopback: true, token_required: false, exec_python: false },
};

describe("requireLiveBridge", () => {
  test("rejects an unreachable bridge in strict live mode", () => {
    expect(() =>
      requireLiveBridge({ ready: false, reason: "connect ECONNREFUSED 127.0.0.1:18710" }),
    ).toThrow(/Cinema 4D bridge not reachable/);
  });

  test("rejects a reachable bridge that is not Cinema 4D 2025", () => {
    expect(() =>
      requireLiveBridge({ ready: true }, { ...validCapabilities, c4d_version: 2026100 }),
    ).toThrow(/Cinema 4D 2025 required.*2026/i);
  });

  test("rejects a 2025 bridge that is not the verified 2025.3.2 build", () => {
    expect(() =>
      requireLiveBridge({ ready: true }, { ...validCapabilities, c4d_version: 2025100 }),
    ).toThrow(/Cinema 4D 2025\.3\.2 required/i);
  });

  test("rejects a non-loopback security snapshot", () => {
    expect(() =>
      requireLiveBridge(
        { ready: true },
        { ...validCapabilities, security: { ...validCapabilities.security, loopback: false } },
      ),
    ).toThrow(/loopback/i);
  });

  test("rejects the wrong platform or bridge version", () => {
    expect(() =>
      requireLiveBridge({ ready: true }, { ...validCapabilities, platform: "darwin" }),
    ).toThrow(/Windows.*win32/i);
    expect(() =>
      requireLiveBridge({ ready: true }, { ...validCapabilities, bridge_version: "0.3.1" }),
    ).toThrow(/bridge 0\.4\.0 required/i);
  });

  test("rejects a mismatched display version or compatibility classification", () => {
    expect(() =>
      requireLiveBridge({ ready: true }, { ...validCapabilities, display_version: "2025.1.0" }),
    ).toThrow(/display_version.*2025\.3\.2/i);
    expect(() =>
      requireLiveBridge({ ready: true }, { ...validCapabilities, compatibility: "unverified" }),
    ).toThrow(/compatibility.*supported/i);
  });

  test("rejects security gates that differ from the test environment", () => {
    expect(() =>
      requireLiveBridge({ ready: true }, validCapabilities, {
        tokenRequired: true,
        execPython: false,
      }),
    ).toThrow(/token_required/i);
  });

  test("accepts the exact verified runtime and security posture", () => {
    expect(() =>
      requireLiveBridge({ ready: true }, validCapabilities, {
        tokenRequired: false,
        execPython: false,
      }),
    ).not.toThrow();
  });
});
