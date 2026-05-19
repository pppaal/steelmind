import { describe, expect, it } from "vitest";
import { deriveApiBase } from "./api";

describe("deriveApiBase", () => {
  const originalEnv = process.env.NEXT_PUBLIC_WS_URL;

  it("converts ws://host:port/ws to http://host:port", () => {
    process.env.NEXT_PUBLIC_WS_URL = "ws://localhost:8000/ws";
    expect(deriveApiBase()).toBe("http://localhost:8000");
  });

  it("converts wss://host/ws to https://host", () => {
    process.env.NEXT_PUBLIC_WS_URL = "wss://example.com/ws";
    expect(deriveApiBase()).toBe("https://example.com");
  });

  it("falls back when env var is missing", () => {
    delete process.env.NEXT_PUBLIC_WS_URL;
    expect(deriveApiBase()).toBe("http://localhost:8000");
    process.env.NEXT_PUBLIC_WS_URL = originalEnv;
  });
});
