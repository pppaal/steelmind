import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RoutineBuilder from "./RoutineBuilder";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function setup(hasChain = false) {
  const onSaved = vi.fn();
  render(
    <RoutineBuilder
      apiBase="http://x"
      behaviors={["wave", "dance"]}
      hasChain={hasChain}
      onSaved={onSaved}
    />,
  );
  return { onSaved };
}

it("is collapsed until opened", () => {
  setup();
  expect(screen.getByRole("button", { name: "+ new routine" })).toBeInTheDocument();
  expect(screen.queryByPlaceholderText("routine name")).toBeNull();
});

it("builds and saves a routine with the assembled steps", async () => {
  const calls: { url: string; method?: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(init.body as string) : null });
      return { ok: true, json: async () => ({ ok: true }) };
    }) as unknown as typeof fetch,
  );
  const { onSaved } = setup();
  fireEvent.click(screen.getByRole("button", { name: "+ new routine" }));

  // name it
  fireEvent.change(screen.getByPlaceholderText("routine name"), { target: { value: "greet" } });

  // add a command step (default type=command, command=stand)
  fireEvent.click(screen.getByRole("button", { name: "add" }));

  // switch to behavior, pick dance, add
  fireEvent.change(screen.getByLabelText("step type"), { target: { value: "behavior" } });
  fireEvent.change(screen.getByLabelText("behavior"), { target: { value: "dance" } });
  fireEvent.click(screen.getByRole("button", { name: "add" }));

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(calls.length).toBe(1));
  const put = calls[0];
  expect(put.method).toBe("PUT");
  expect(put.url).toBe("http://x/routines/greet");
  expect(put.body).toEqual({
    steps: [
      { type: "command", command: "stand" },
      { type: "behavior", behavior: "dance" },
    ],
  });
  expect(onSaved).toHaveBeenCalled();
});

it("blocks save with no name", async () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "+ new routine" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("name required")).toBeInTheDocument();
});

it("hides the reach option when there is no chain", () => {
  setup(false);
  fireEvent.click(screen.getByRole("button", { name: "+ new routine" }));
  const options = Array.from(screen.getByLabelText("step type").querySelectorAll("option")).map(
    (o) => o.getAttribute("value"),
  );
  expect(options).not.toContain("reach");
});

it("shows the reach option when a chain exists", () => {
  setup(true);
  fireEvent.click(screen.getByRole("button", { name: "+ new routine" }));
  const options = Array.from(screen.getByLabelText("step type").querySelectorAll("option")).map(
    (o) => o.getAttribute("value"),
  );
  expect(options).toContain("reach");
});

it("hides the AI input unless aiEnabled", () => {
  render(
    <RoutineBuilder apiBase="http://x" behaviors={["wave"]} hasChain={false} onSaved={() => {}} />,
  );
  expect(screen.queryByPlaceholderText("AI: describe a routine…")).toBeNull();
});

it("posts to /ai-routine when the AI generate button is used", async () => {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : null });
      return { ok: true, json: async () => ({ ok: true, steps: [] }) };
    }) as unknown as typeof fetch,
  );
  const onSaved = vi.fn();
  render(
    <RoutineBuilder apiBase="http://x" behaviors={["wave"]} hasChain={false} onSaved={onSaved} aiEnabled />,
  );
  fireEvent.change(screen.getByPlaceholderText("AI: describe a routine…"), {
    target: { value: "wave then sit" },
  });
  fireEvent.click(screen.getByRole("button", { name: "gen" }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/ai-routine"))).toBe(true));
  const gen = calls.find((c) => c.url.endsWith("/ai-routine"))!;
  expect((gen.body as { text: string }).text).toBe("wave then sit");
  expect(onSaved).toHaveBeenCalled();
});
