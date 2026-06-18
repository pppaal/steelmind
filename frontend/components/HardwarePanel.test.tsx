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

  it("jogs a joint with the right payload on press", async () => {
    // Record on the fetch call itself (jogOnce only reads .json() on error).
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.body) calls.push({ url, body: JSON.parse(init.body as string) });
        return { ok: true, json: async () => ({ keyframes: {} }) };
      }) as unknown as typeof fetch,
    );
    render(<HardwarePanel apiBase="http://x" jointNames={["shoulder_right"]} />);
    const plus = screen.getByRole("button", { name: "jog shoulder_right positive" });
    fireEvent.pointerDown(plus);
    fireEvent.pointerUp(plus);
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/jog"))).toBe(true));
    const jog = calls.find((c) => c.url.endsWith("/jog"))!;
    expect((jog.body as { joint: string }).joint).toBe("shoulder_right");
    expect((jog.body as { delta: number }).delta).toBeGreaterThan(0);
  });

  it("repeats jog while held and stops on release", async () => {
    vi.useFakeTimers();
    let jogCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/jog")) jogCount += 1;
        return { ok: true, json: async () => ({ keyframes: {} }) };
      }) as unknown as typeof fetch,
    );
    try {
      render(<HardwarePanel apiBase="http://x" jointNames={["j1"]} />);
      const minus = screen.getByRole("button", { name: "jog j1 negative" });
      fireEvent.pointerDown(minus); // immediate jog
      // Let the immediate jog's promise settle, then advance the repeat timer.
      await vi.advanceTimersByTimeAsync(0);
      const afterPress = jogCount;
      expect(afterPress).toBeGreaterThanOrEqual(1);
      await vi.advanceTimersByTimeAsync(500); // ~3 more repeats at 150ms
      const afterHold = jogCount;
      expect(afterHold).toBeGreaterThan(afterPress);
      fireEvent.pointerUp(minus);
      const atRelease = jogCount;
      await vi.advanceTimersByTimeAsync(500);
      // No more jogs after release.
      expect(jogCount).toBe(atRelease);
    } finally {
      vi.useRealTimers();
    }
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

  it("reflects a server-side e-stop and recovers when it clears", async () => {
    vi.stubGlobal("fetch", mockFetch(() => ({ keyframes: {} })));
    const { rerender } = render(
      <HardwarePanel apiBase="http://x" jointNames={[]} serverEstopped={false} />,
    );
    // Starts live: the big red E-STOP button is shown.
    expect(screen.getByRole("button", { name: /E-STOP/ })).toBeInTheDocument();
    // Server latches an e-stop (watchdog / another operator) — panel must follow.
    rerender(<HardwarePanel apiBase="http://x" jointNames={[]} serverEstopped={true} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Clear E-Stop/ })).toBeInTheDocument(),
    );
    // Server clears it — panel returns to live.
    rerender(<HardwarePanel apiBase="http://x" jointNames={[]} serverEstopped={false} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /E-STOP/ })).toBeInTheDocument(),
    );
  });

  it("stops an active jog hold when a server e-stop latches", async () => {
    vi.useFakeTimers();
    let jogCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/jog")) jogCount += 1;
        return { ok: true, json: async () => ({ keyframes: {} }) };
      }) as unknown as typeof fetch,
    );
    try {
      const { rerender } = render(
        <HardwarePanel apiBase="http://x" jointNames={["j1"]} serverEstopped={false} />,
      );
      fireEvent.pointerDown(screen.getByRole("button", { name: "jog j1 positive" }));
      await vi.advanceTimersByTimeAsync(300);
      expect(jogCount).toBeGreaterThan(0);
      // Server e-stop arrives mid-hold: the repeat interval must be cancelled.
      rerender(<HardwarePanel apiBase="http://x" jointNames={["j1"]} serverEstopped={true} />);
      const atEstop = jogCount;
      await vi.advanceTimersByTimeAsync(500);
      expect(jogCount).toBe(atEstop);
    } finally {
      vi.useRealTimers();
    }
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

  it("warns and blocks Reach when the target is outside the workspace annulus", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch((url) => {
        if (url.endsWith("/fk")) return { x: 0.2, y: 0.1, reach: 0.32 };
        if (url.endsWith("/workspace"))
          return { base: [0, 0], inner_radius: 0.05, outer_radius: 0.3, reach: 0.32 };
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={["shoulder_lift"]} />);
    // Default target (0.15, 0.10) is inside → Reach enabled.
    const btn = await screen.findByRole("button", { name: "Reach" });
    await waitFor(() => expect(btn).not.toBeDisabled());
    // Push x far beyond the outer radius → blocked with a warning.
    const xInput = screen.getByDisplayValue("0.15");
    fireEvent.change(xInput, { target: { value: "5" } });
    await waitFor(() => expect(screen.getByText(/beyond reach/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Reach" })).toBeDisabled();
  });

  it("blocks Reach when the target violates a safety zone (virtual wall)", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch((url) => {
        if (url.endsWith("/fk")) return { x: 0.2, y: 0.1, reach: 0.32 };
        if (url.endsWith("/workspace"))
          return {
            base: [0, 0],
            inner_radius: 0.0,
            outer_radius: 0.5,
            zone: { min_x: null, max_x: null, min_y: 0.0, max_y: null, min_radius: null, keepout: [], base: [0, 0] },
          };
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={["shoulder_lift"]} />);
    const xInput = await screen.findByDisplayValue("0.15");
    // y below the floor (min_y = 0) → blocked even though it's within reach.
    const yInput = screen.getByDisplayValue("0.10");
    fireEvent.change(yInput, { target: { value: "-0.2" } });
    await waitFor(() => expect(screen.getByText(/outside safe zone/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Reach" })).toBeDisabled();
    // Bring it back inside → unblocked.
    fireEvent.change(yInput, { target: { value: "0.1" } });
    fireEvent.change(xInput, { target: { value: "0.15" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Reach" })).not.toBeDisabled());
  });

  it("previews a reach (dry_run) without moving the robot", async () => {
    const calls: { url: string; body: { dry_run?: boolean } }[] = [];
    vi.stubGlobal(
      "fetch",
      mockFetch((url, init) => {
        if (init?.body) calls.push({ url, body: JSON.parse(init.body as string) });
        if (url.endsWith("/fk")) return { x: 0.2, y: 0.1, reach: 0.32 };
        if (url.endsWith("/workspace"))
          return { base: [0, 0], inner_radius: 0.05, outer_radius: 0.3, reach: 0.32 };
        if (url.endsWith("/reach"))
          return {
            dry_run: true,
            reached: true,
            preview: { violations: [{ kind: "velocity", detail: "peak 3.9 rad/s over max_velocity" }], path: { end: [0.15, 0.1] } },
          };
        return { keyframes: {} };
      }),
    );
    render(<HardwarePanel apiBase="http://x" jointNames={["shoulder_lift"]} />);
    const preview = await screen.findByRole("button", { name: "Preview" });
    fireEvent.click(preview);
    await waitFor(() => expect(screen.getByText(/dry run: reachable/i)).toBeInTheDocument());
    // The dry-run call carried dry_run: true.
    const reachCall = calls.find((c) => c.url.endsWith("/reach"));
    expect(reachCall?.body.dry_run).toBe(true);
    expect(screen.getByText(/over max_velocity/i)).toBeInTheDocument();
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
