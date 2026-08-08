import { describe, expect, test } from "vitest";
import { classifyC4DVersion } from "../../src/compatibility-policy.js";

describe("classifyC4DVersion", () => {
  test("marks Cinema 4D 2025 builds as supported", () => {
    expect(classifyC4DVersion(2025302)).toEqual({
      release: 2025,
      status: "supported",
      display: "2025.3.2",
    });
  });

  test.each([2024000, 2026000])("marks %i as unverified", (raw) => {
    expect(classifyC4DVersion(raw).status).toBe("unverified");
  });

  test.each([0, -1, Number.NaN])("rejects malformed version %s", (raw) => {
    expect(classifyC4DVersion(raw).status).toBe("unsupported");
  });
});
