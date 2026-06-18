import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TelemetryPanel from "./TelemetryPanel";
import { emptyState } from "@/lib/socketReducer";
import type { SensorData } from "@/lib/types";

const V0 = { x: 0, y: 0, z: 0 };

function sensor(extra: Partial<SensorData> = {}): SensorData {
  return {
    timestamp: new Date().toISOString(),
    imu_orientation: V0,
    imu_angular_velocity: V0,
    imu_linear_acceleration: V0,
    joint_positions: { j1: 0.1 },
    joint_velocities: { j1: 0 },
    battery_voltage: 24,
    battery_percent: 80,
    ...extra,
  };
}

describe("TelemetryPanel joint load", () => {
  it("renders a load section when efforts are present", () => {
    render(
      <TelemetryPanel
        connection="open"
        status={null}
        sensor={sensor({ joint_efforts: { j1: 1.5, j2: 0.5 } })}
        history={emptyState().history}
        lastReason={null}
      />,
    );
    expect(screen.getByText(/Joint Load/i)).toBeInTheDocument();
    // Both joints' effort values are shown.
    expect(screen.getByText("1.50")).toBeInTheDocument();
    expect(screen.getByText("0.50")).toBeInTheDocument();
  });

  it("omits the load section when no efforts are reported", () => {
    render(
      <TelemetryPanel
        connection="open"
        status={null}
        sensor={sensor()}
        history={emptyState().history}
        lastReason={null}
      />,
    );
    expect(screen.queryByText(/Joint Load/i)).toBeNull();
  });
});
