import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import AICommandInput from "./AICommandInput";

const OK_PLAN = { explanation: "ok", steps: [{ command: "stand", params: {} }], repaired: false };

function stubFetch(cameraAvailable: boolean, calls: { url: string; body: unknown }[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/camera/info")) {
        return { ok: true, json: async () => ({ available: cameraAvailable }) };
      }
      if (url.endsWith("/ai-command")) {
        calls.push({ url, body: JSON.parse(init!.body as string) });
        return { ok: true, json: async () => OK_PLAN };
      }
      return { ok: true, json: async () => ({}) };
    }) as unknown as typeof fetch,
  );
}

beforeEach(() => vi.stubGlobal("localStorage", {
  getItem: () => "sid", setItem: () => {}, removeItem: () => {},
}));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("sends the camera frame when vision is toggled on", async () => {
  const calls: { url: string; body: unknown }[] = [];
  stubFetch(true, calls);
  render(<AICommandInput />);
  const toggle = await screen.findByRole("button", { name: /vision/i });
  fireEvent.click(toggle); // arm vision
  fireEvent.change(screen.getByPlaceholderText(/자연어로 명령/), { target: { value: "stand" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(calls.length).toBe(1));
  expect((calls[0].body as { use_vision: boolean }).use_vision).toBe(true);
});

it("hides the vision toggle and stays text-only when no camera", async () => {
  const calls: { url: string; body: unknown }[] = [];
  stubFetch(false, calls);
  render(<AICommandInput />);
  // No camera → no toggle.
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /vision/i })).toBeNull(),
  );
  fireEvent.change(screen.getByPlaceholderText(/자연어로 명령/), { target: { value: "stand" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(calls.length).toBe(1));
  expect((calls[0].body as { use_vision: boolean }).use_vision).toBe(false);
});
