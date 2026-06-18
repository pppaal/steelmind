import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Sparkline from "./Sparkline";

function pointCoords(container: HTMLElement): string {
  const poly = container.querySelector("polyline");
  return poly?.getAttribute("points") ?? "";
}

describe("Sparkline", () => {
  it("renders a polyline for finite data", () => {
    const { container } = render(<Sparkline data={[0, 1, 2, 3]} />);
    const pts = pointCoords(container);
    expect(pts).not.toBe("");
    expect(pts).not.toMatch(/NaN/);
  });

  it("drops NaN/Infinity samples instead of poisoning the whole chart", () => {
    const { container } = render(<Sparkline data={[0, NaN, 2, Infinity, 4]} />);
    const pts = pointCoords(container);
    // A single bad value would make Math.min/max NaN and break every point.
    expect(pts).not.toBe("");
    expect(pts).not.toMatch(/NaN|Infinity/);
  });

  it("falls back to the flat baseline when too few finite points remain", () => {
    const { container } = render(<Sparkline data={[NaN, 5]} />);
    // Only one finite sample → no polyline, just the dashed baseline.
    expect(container.querySelector("polyline")).toBeNull();
    expect(container.querySelector("line")).not.toBeNull();
  });
});
