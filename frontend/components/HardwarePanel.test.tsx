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

  it("shows the Reach panel only when /fk returns a position, and sends x/y", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      mockFetch((url, init) => {
        if (init?.body) calls.push({ url, body: JSON.parse(init.body as string) });
        if (url.endsWith("/fk")) return { x: 0.2, y: 0.1, reach: 0.32 };
        if (url.endsWith("/reach")) return { reached: true, angles: {} };
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={["shoulder_lift"]} />);
    const btn = await screen.findByRole("button", { name: "Reach" });
    fireEvent.click(btn);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/reach"))).toBe(true));
    const reach = calls.find((c) => c.url.endsWith("/reach"))!;
    expect(reach.body).toMatchObject({ x: 0.15, y: 0.1 });
  });

  it("imports a routine file via PUT", async () => {
    const calls: { url: string; method?: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      mockFetch((url, init) => {
        calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(init.body as string) : null });
        return { keyframes: {}, routines: {}, behaviors: [] };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={[]} />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const json = JSON.stringify({ name: "greet", steps: [{ type: "command", command: "stand" }] });
    const file = new File([json], "routine-greet.json", { type: "application/json" });
    // jsdom's File doesn't implement .text(); provide it for the component.
    Object.defineProperty(file, "text", { value: async () => json });
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() =>
      expect(calls.some((c) => c.method === "PUT" && c.url.endsWith("/routines/greet"))).toBe(true),
    );
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({ steps: [{ type: "command", command: "stand" }] });
  });
});
