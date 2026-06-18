import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EventLog from "./EventLog";
import type { LogEntry } from "@/lib/useRobotSocket";

function transition(id: number): LogEntry {
  return {
    id,
    t: new Date().toISOString(),
    kind: "transition",
    from: "IDLE",
    to: "STANDING",
    reason: "command:stand",
  };
}

describe("EventLog", () => {
  it("auto-scrolls to the newest entry while pinned to the bottom", () => {
    // jsdom reports 0 for layout sizes, so scrollHeight - scrollTop -
    // clientHeight === 0 < 24 → considered "at bottom" (the default).
    const { container, rerender } = render(<EventLog entries={[transition(1)]} />);
    const scroller = container.querySelector(".overflow-y-auto") as HTMLDivElement;
    Object.defineProperty(scroller, "scrollHeight", { value: 500, configurable: true });
    const spy = vi.spyOn(scroller, "scrollTop", "set");
    rerender(<EventLog entries={[transition(1), transition(2)]} />);
    expect(spy).toHaveBeenCalledWith(500);
  });

  it("does not yank the view down when the user has scrolled up", () => {
    const { container, rerender } = render(<EventLog entries={[transition(1)]} />);
    const scroller = container.querySelector(".overflow-y-auto") as HTMLDivElement;
    // Simulate the user scrolling up: far from the bottom.
    Object.defineProperty(scroller, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(scroller, "clientHeight", { value: 100, configurable: true });
    Object.defineProperty(scroller, "scrollTop", { value: 0, writable: true, configurable: true });
    scroller.dispatchEvent(new Event("scroll"));
    const spy = vi.spyOn(scroller, "scrollTop", "set");
    rerender(<EventLog entries={[transition(1), transition(2)]} />);
    expect(spy).not.toHaveBeenCalled();
  });
});
