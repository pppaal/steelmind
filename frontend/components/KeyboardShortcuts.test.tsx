import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import KeyboardShortcuts from "./KeyboardShortcuts";

describe("KeyboardShortcuts", () => {
  it("routes 1/2/3/4 to idle/stand/walk/execute", () => {
    const onCommand = vi.fn();
    render(<KeyboardShortcuts enabled onCommand={onCommand} />);
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "3" });
    fireEvent.keyDown(window, { key: "4" });
    expect(onCommand).toHaveBeenNthCalledWith(1, "idle", undefined);
    expect(onCommand).toHaveBeenNthCalledWith(2, "stand", undefined);
    expect(onCommand).toHaveBeenNthCalledWith(3, "walk", undefined);
    expect(onCommand).toHaveBeenNthCalledWith(4, "execute", { behavior: "demo" });
  });

  it("ignores keystrokes while focus is in an input", () => {
    const onCommand = vi.fn();
    const { container } = render(
      <>
        <input data-testid="ip" />
        <KeyboardShortcuts enabled onCommand={onCommand} />
      </>,
    );
    const input = container.querySelector("input")!;
    input.focus();
    fireEvent.keyDown(input, { key: "1" });
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("no-ops when disabled", () => {
    const onCommand = vi.fn();
    render(<KeyboardShortcuts enabled={false} onCommand={onCommand} />);
    fireEvent.keyDown(window, { key: "1" });
    expect(onCommand).not.toHaveBeenCalled();
  });
});
