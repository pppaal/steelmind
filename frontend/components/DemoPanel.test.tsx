import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DemoPanel from "./DemoPanel";

describe("DemoPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("starts an episode and labels it success", async () => {
    let active = false;
    const posts: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          posts.push({ url, body: init.body ? JSON.parse(init.body as string) : null });
          active = url.endsWith("/demos/start");
          return { ok: true, json: async () => ({ active, episodes: active ? 0 : 1 }) };
        }
        return { ok: true, json: async () => ({ active, episodes: 0, current_frames: 0 }) };
      }) as unknown as typeof fetch,
    );
    render(<DemoPanel apiBase="http://x" />);
    const taskInput = await screen.findByPlaceholderText("task");
    fireEvent.change(taskInput, { target: { value: "pick cube" } });
    fireEvent.click(screen.getByRole("button", { name: /record/i }));
    await waitFor(() => expect(posts.some((p) => p.url.endsWith("/demos/start"))).toBe(true));
    expect((posts[0].body as { task: string }).task).toBe("pick cube");
    // Now recording → success/fail controls appear.
    await waitFor(() => expect(screen.getByRole("button", { name: /success/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /success/i }));
    await waitFor(() =>
      expect(posts.some((p) => p.url.endsWith("/demos/stop") && (p.body as { success: boolean }).success === true)).toBe(true),
    );
  });

  it("disables download with no episodes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ active: false, episodes: 0 }) })) as unknown as typeof fetch,
    );
    render(<DemoPanel apiBase="http://x" />);
    const dl = await screen.findByRole("button", { name: /download/i });
    expect(dl).toBeDisabled();
  });
});
