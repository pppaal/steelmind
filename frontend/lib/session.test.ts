import { beforeEach, describe, expect, it } from "vitest";
import { getSessionId } from "./session";

describe("getSessionId", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns the same id across calls", () => {
    const a = getSessionId();
    const b = getSessionId();
    expect(a).toBe(b);
    expect(a.length).toBeGreaterThan(5);
  });

  it("persists in localStorage", () => {
    const id = getSessionId();
    expect(window.localStorage.getItem("steelmind_session_id")).toBe(id);
  });
});
