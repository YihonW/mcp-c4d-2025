import { describe, expect, test } from "vitest";

import { closeDocumentIfPresent } from "../e2e/harness.js";

class FakeDocumentClient {
  readonly calls: Array<{ name: string; args: Record<string, unknown> }> = [];
  private present = true;

  async call<T>(name: string, args: Record<string, unknown> = {}): Promise<T> {
    this.calls.push({ name, args });
    if (name === "list_documents") {
      return {
        documents: this.present ? [{ index: 1, name: "e2e-temp", path: "", active: false }] : [],
      } as T;
    }
    if (name === "close_document") {
      this.present = false;
      return { closed_document: "e2e-temp" } as T;
    }
    throw new Error(`unexpected call: ${name}`);
  }
}

describe("closeDocumentIfPresent", () => {
  test("finds and force-closes a named temporary document idempotently", async () => {
    const client = new FakeDocumentClient();

    await closeDocumentIfPresent(client, "e2e-temp");
    await closeDocumentIfPresent(client, "e2e-temp");

    expect(client.calls).toEqual([
      { name: "list_documents", args: {} },
      { name: "close_document", args: { name: "e2e-temp", force: true } },
      { name: "list_documents", args: {} },
    ]);
  });

  test("does not hide failures while checking whether the document exists", async () => {
    const client = {
      async call(): Promise<never> {
        throw new Error("bridge disconnected");
      },
    };

    await expect(closeDocumentIfPresent(client, "e2e-temp")).rejects.toThrow("bridge disconnected");
  });

  test("refuses to close when the temporary document name is not unique", async () => {
    const client = {
      async call<T>(name: string): Promise<T> {
        if (name !== "list_documents") throw new Error(`unexpected call: ${name}`);
        return {
          documents: [{ name: "e2e-temp" }, { name: "e2e-temp" }],
        } as T;
      },
    };

    await expect(closeDocumentIfPresent(client, "e2e-temp")).rejects.toThrow(
      /refusing to close 2 documents/,
    );
  });
});
