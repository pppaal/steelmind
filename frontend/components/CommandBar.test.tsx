import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CommandBar from "./CommandBar";

const sampleBehaviors = {
  behaviors: [
    { name: "demo", description: "demo behavior" },
    { name: "wave", description: "wave behavior" },
  ],
};

describe("CommandBar", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => sampleBehaviors,
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("calls onCommand with stand when Stand is clicked", async () => {
    const onCommand = vi.fn();
    render(<CommandBar state="IDLE" disabled={false} onCommand={onCommand} apiBase="http://x" />);
    await waitFor(() => expect(screen.getByRole("option", { name: "wave" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^Stand$/ }));
    expect(onCommand).toHaveBeenCalledWith("stand");
  });

  it("disables buttons when disabled prop is true", async () => {
    render(<CommandBar state="IDLE" disabled={true} onCommand={() => {}} apiBase="http://x" />);
    await waitFor(() => expect(screen.getByRole("option", { name: "wave" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Stand$/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Execute$/ })).toBeDisabled();
  });

  it("fetches behaviors and sends selected behavior with Execute", async () => {
    const onCommand = vi.fn();
    render(<CommandBar state="STANDING" disabled={false} onCommand={onCommand} apiBase="http://x" />);
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "wave" })).toBeInTheDocument();
    });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "wave" } });
    fireEvent.click(screen.getByRole("button", { name: /^Execute$/ }));
    expect(onCommand).toHaveBeenCalledWith("execute", { behavior: "wave" });
  });
});
