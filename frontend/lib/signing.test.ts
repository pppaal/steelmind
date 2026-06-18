import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { signCommand, stableStringify } from "./api";

describe("command signing", () => {
  it("stableStringify is compact and recursively key-sorted", () => {
    expect(stableStringify({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
    expect(stableStringify({})).toBe("{}");
    // Nested objects sort too; arrays keep order — matches Python json.dumps
    // (sort_keys=True, separators=(",",":")).
    expect(stableStringify({ z: { y: 1, x: 2 }, a: [3, 1] })).toBe(
      '{"a":[3,1],"z":{"x":2,"y":1}}',
    );
  });

  it("signCommand matches an independent HMAC-SHA256 over the canonical string", async () => {
    const key = "operator-secret";
    const ts = 1718000000;
    const nonce = "n1";
    const params = { behavior: "wave" };
    const got = await signCommand(key, "stand", params, ts, nonce);

    const canonical = `${ts}:${nonce}:stand:${stableStringify(params)}`;
    const expected = createHmac("sha256", key).update(canonical).digest("hex");
    expect(got).toBe(expected);
    expect(got).toMatch(/^[0-9a-f]{64}$/);
  });

  it("different inputs produce different signatures", async () => {
    const a = await signCommand("k", "stand", {}, 1, "n");
    const b = await signCommand("k", "walk", {}, 1, "n");
    expect(a).not.toBe(b);
  });
});
