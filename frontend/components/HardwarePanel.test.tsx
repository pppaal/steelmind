import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HardwarePanel from "./HardwarePanel";

function mockFetch(handler: (url: string, init?: RequestInit) => unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => ({
    ok: true,
    json: async () => handler(url, init),
  })) as unknown as typeof fetch;
}

describe("HardwarePanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch(() => ({ keyframes: {} })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("jogs a joint with the right payload", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      mockFetch((url, init) => {
        if (init?.body) calls.push({ url, body: JSON.parse(init.body as string) });
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={["shoulder_right"]} />);
    fireEvent.click(screen.getAllByRole("button", { name: "+" })[0]);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/jog"))).toBe(true));
    const jog = calls.find((c) => c.url.endsWith("/jog"))!;
    expect((jog.body as { joint: string }).joint).toBe("shoulder_right");
    expect((jog.body as { delta: number }).delta).toBeGreaterThan(0);
  });

  it("fires estop then shows clear button", async () => {
    const hit: string[] = [];
    vi.stubGlobal(
      "fetch",
      mockFetch((url) => {
        hit.push(url);
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /E-STOP/ }));
    await waitFor(() => expect(hit.some((u) => u.endsWith("/estop"))).toBe(true));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Clear E-Stop/ })).toBeInTheDocument(),
    );
  });

  it("records a keyframe", async () => {
    const hit: string[] = [];
    vi.stubGlobal(
      "fetch",
      mockFetch((url) => {
        hit.push(url);
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={[]} />);
    fireEvent.change(screen.getByPlaceholderText("keyframe name"), {
      target: { value: "home" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() =>
      expect(hit.some((u) => u.endsWith("/keyframes/home"))).toBe(true),
    );
  });
});
