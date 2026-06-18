import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CameraPanel from "./CameraPanel";

describe("CameraPanel", () => {
  beforeEach(() => {
    // jsdom lacks object-URL APIs; add them (don't replace URL wholesale, so
    // its constructor survives and cleanup ordering can't strip them mid-test).
    URL.createObjectURL = vi.fn(() => "blob:fake");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows the feed when a camera is available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/camera/info")) {
          return { ok: true, json: async () => ({ available: true, width: 160, height: 120 }) };
        }
        // snapshot
        return { ok: true, blob: async () => new Blob([new Uint8Array([66, 77])]) };
      }) as unknown as typeof fetch,
    );
    render(<CameraPanel apiBase="http://x" intervalMs={10} />);
    const img = (await screen.findByAltText("robot camera")) as HTMLImageElement;
    await waitFor(() => expect(img.getAttribute("src")).toBe("blob:fake"));
    expect(screen.getByText(/camera/i)).toBeInTheDocument();
  });

  it("renders nothing when no camera is available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ available: false }) })) as unknown as typeof fetch,
    );
    const { container } = render(<CameraPanel apiBase="http://x" />);
    await waitFor(() => expect(container.firstChild).toBeNull());
    expect(screen.queryByAltText("robot camera")).toBeNull();
  });
});
