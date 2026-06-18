import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRobotSocket } from "./useRobotSocket";

// Minimal WebSocket stand-in so we can drive open/close lifecycle by hand.
class FakeWS {
  static OPEN = 1;
  static instances: FakeWS[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  open() {
    this.readyState = FakeWS.OPEN;
    this.onopen?.();
  }
  send = vi.fn();
  close() {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.();
  }
}

describe("useRobotSocket", () => {
  beforeEach(() => {
    FakeWS.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not reconnect after the hook unmounts", () => {
    const { unmount } = renderHook(() => useRobotSocket());
    expect(FakeWS.instances).toHaveLength(1);
    const first = FakeWS.instances[0];
    act(() => first.open());

    // Unmount: the cleanup closes the socket. Its onclose must NOT schedule a
    // reconnect, so no new socket appears even after the reconnect delay.
    unmount();
    act(() => vi.advanceTimersByTime(5000));
    expect(FakeWS.instances).toHaveLength(1);
  });

  it("reconnects when a live socket closes unexpectedly", () => {
    renderHook(() => useRobotSocket());
    const first = FakeWS.instances[0];
    act(() => first.open());
    // Server drops the connection while still mounted.
    act(() => first.close());
    act(() => vi.advanceTimersByTime(1500));
    expect(FakeWS.instances).toHaveLength(2);
  });
});
