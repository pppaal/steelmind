import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RecordingPanel from "./RecordingPanel";

describe("RecordingPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("toggles recording start/stop via the API", async () => {
    let active = false;
    let count = 0;
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          posts.push(url);
          active = url.endsWith("/recording/start");
          count = active ? 0 : 2;
          return { ok: true, json: async () => ({ active, count }) };
        }
        // GET /recording status
        return { ok: true, json: async () => ({ active, count }) };
      }) as unknown as typeof fetch,
    );
    render(<RecordingPanel apiBase="http://x" />);
    const btn = await screen.findByRole("button", { name: /record/i });
    fireEvent.click(btn);
    await waitFor(() => expect(posts.some((u) => u.endsWith("/recording/start"))).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: /recording/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /recording/i }));
    await waitFor(() => expect(posts.some((u) => u.endsWith("/recording/stop"))).toBe(true));
  });

  it("starts a replay via the API", async () => {
    let replaying = false;
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          posts.push(url);
          replaying = url.endsWith("/recording/replay");
          return { ok: true, json: async () => ({ replaying }) };
        }
        return { ok: true, json: async () => ({ active: false, count: 3, replaying }) };
      }) as unknown as typeof fetch,
    );
    render(<RecordingPanel apiBase="http://x" />);
    const replay = await screen.findByRole("button", { name: /replay/i });
    await waitFor(() => expect(replay).not.toBeDisabled()); // count>0, not recording
    fireEvent.click(replay);
    await waitFor(() => expect(posts.some((u) => u.endsWith("/recording/replay"))).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument());
  });

  it("downloads the exported timeline", async () => {
    URL.createObjectURL = vi.fn(() => "blob:fake");
    URL.revokeObjectURL = vi.fn();
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/recording/export")) {
          return { ok: true, blob: async () => new Blob(["{}"]) };
        }
        return { ok: true, json: async () => ({ active: false, count: 5 }) };
      }) as unknown as typeof fetch,
    );
    render(<RecordingPanel apiBase="http://x" />);
    const dl = await screen.findByRole("button", { name: /download/i });
    await waitFor(() => expect(dl).not.toBeDisabled()); // count > 0 enables it
    fireEvent.click(dl);
    await waitFor(() => expect(clickSpy).toHaveBeenCalled());
  });
});
