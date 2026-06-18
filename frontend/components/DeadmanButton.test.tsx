import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DeadmanButton from "./DeadmanButton";

describe("DeadmanButton", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("pings on press and repeats while held, then stops on release", () => {
    const onPing = vi.fn();
    render(<DeadmanButton onPing={onPing} enabled intervalMs={100} />);
    const btn = screen.getByRole("button");

    fireEvent.pointerDown(btn); // immediate ping
    expect(onPing).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(250); // +2 interval pings
    expect(onPing).toHaveBeenCalledTimes(3);

    fireEvent.pointerUp(btn);
    const atRelease = onPing.mock.calls.length;
    vi.advanceTimersByTime(500);
    expect(onPing).toHaveBeenCalledTimes(atRelease); // no pings after release
  });

  it("stops pinging when the pointer leaves the button", () => {
    const onPing = vi.fn();
    render(<DeadmanButton onPing={onPing} enabled intervalMs={100} />);
    const btn = screen.getByRole("button");
    fireEvent.pointerDown(btn);
    fireEvent.pointerLeave(btn);
    const atLeave = onPing.mock.calls.length;
    vi.advanceTimersByTime(500);
    expect(onPing).toHaveBeenCalledTimes(atLeave);
  });

  it("does not ping when disabled (disconnected)", () => {
    const onPing = vi.fn();
    render(<DeadmanButton onPing={onPing} enabled={false} intervalMs={100} />);
    fireEvent.pointerDown(screen.getByRole("button"));
    vi.advanceTimersByTime(500);
    expect(onPing).not.toHaveBeenCalled();
  });
});
