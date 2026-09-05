import { describe, expect, test } from "vitest";

import { requireRedshiftCapabilities } from "../e2e/harness.js";

const validCapabilities = {
  renderer: { supported: true, id: 1036219 },
  module: { supported: true },
  node_space: {
    supported: true,
    id: "com.redshift3d.redshift4c4d.class.nodespace",
    node_template_count: 12,
  },
  aov_api: { supported: true, aliases: { beauty: 10 } },
  materials: { supported: true },
  lights: {
    supported: true,
    types: { area: { supported: true }, dome: { supported: true } },
  },
  camera: { supported: true },
  render: { supported: true },
};

describe("requireRedshiftCapabilities", () => {
  test("rejects the wrong renderer, module, or node-space identity", () => {
    expect(() =>
      requireRedshiftCapabilities({
        ...validCapabilities,
        renderer: { supported: true, id: 1 },
      }),
    ).toThrow(/renderer.*1036219/i);
    expect(() =>
      requireRedshiftCapabilities({ ...validCapabilities, module: { supported: false } }),
    ).toThrow(/module/i);
    expect(() =>
      requireRedshiftCapabilities({
        ...validCapabilities,
        node_space: { ...validCapabilities.node_space, id: "wrong" },
      }),
    ).toThrow(/node.space/i);
    expect(() =>
      requireRedshiftCapabilities({
        ...validCapabilities,
        node_space: { ...validCapabilities.node_space, node_template_count: 0 },
      }),
    ).toThrow(/node.template.count/i);
  });

  test("rejects missing AOV mutation support or aliases", () => {
    expect(() =>
      requireRedshiftCapabilities({
        ...validCapabilities,
        aov_api: { supported: false, aliases: {} },
      }),
    ).toThrow(/AOV API/i);
    expect(() =>
      requireRedshiftCapabilities({
        ...validCapabilities,
        aov_api: { supported: true, aliases: {} },
      }),
    ).toThrow(/AOV.*alias/i);
  });

  test("rejects unavailable materials, Area/Dome lights, camera, or render", () => {
    expect(() =>
      requireRedshiftCapabilities({ ...validCapabilities, materials: { supported: false } }),
    ).toThrow(/materials/i);
    for (const type of ["area", "dome"] as const) {
      expect(() =>
        requireRedshiftCapabilities({
          ...validCapabilities,
          lights: {
            ...validCapabilities.lights,
            types: {
              ...validCapabilities.lights.types,
              [type]: { supported: false },
            },
          },
        }),
      ).toThrow(new RegExp(type, "i"));
    }
    expect(() =>
      requireRedshiftCapabilities({ ...validCapabilities, camera: { supported: false } }),
    ).toThrow(/camera/i);
    expect(() =>
      requireRedshiftCapabilities({ ...validCapabilities, render: { supported: false } }),
    ).toThrow(/render/i);
  });

  test("accepts only the complete expected Redshift snapshot", () => {
    expect(() => requireRedshiftCapabilities(validCapabilities)).not.toThrow();
  });
});
