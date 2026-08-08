import { describe, expect, test } from "vitest";

import { MCPTestClient, probeBridge, requireLiveBridge } from "../e2e/harness.js";

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

describe("probeBridge live opt-in", () => {
  test("does not start an MCP client when live E2E was not explicitly enabled", async () => {
    const originalConnect = MCPTestClient.prototype.connect;
    const priorAllow = process.env.C4D_MCP_ALLOW_LIVE_E2E;
    const priorStrict = process.env.C4D_MCP_REQUIRE_LIVE;
    let connectionAttempts = 0;

    MCPTestClient.prototype.connect = async () => {
      connectionAttempts += 1;
    };
    delete process.env.C4D_MCP_ALLOW_LIVE_E2E;
    delete process.env.C4D_MCP_REQUIRE_LIVE;

    try {
      const result = await probeBridge("unit-offline-policy");

      expect(result).toMatchObject({
        ready: false,
        reason: expect.stringMatching(/explicit live opt-in/i),
      });
      expect(connectionAttempts).toBe(0);
    } finally {
      MCPTestClient.prototype.connect = originalConnect;
      if (priorAllow === undefined) delete process.env.C4D_MCP_ALLOW_LIVE_E2E;
      else process.env.C4D_MCP_ALLOW_LIVE_E2E = priorAllow;
      if (priorStrict === undefined) delete process.env.C4D_MCP_REQUIRE_LIVE;
      else process.env.C4D_MCP_REQUIRE_LIVE = priorStrict;
    }
  });
});
