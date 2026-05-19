import { describe, expect, it } from "vitest";
import {
  HISTORY_LEN,
  LOG_LEN,
  emptyState,
  pushBounded,
  reduce,
} from "./socketReducer";
import type { SensorEvent, StateTransitionEvent, AICommandEvent, StatusEvent } from "./types";

describe("pushBounded", () => {
  it("appends until max then evicts oldest", () => {
    let arr: number[] = [];
    for (let i = 0; i < HISTORY_LEN + 5; i++) arr = pushBounded(arr, i);
    expect(arr.length).toBe(HISTORY_LEN);
    expect(arr[0]).toBe(5);
    expect(arr[HISTORY_LEN - 1]).toBe(HISTORY_LEN + 4);
  });

  it("respects custom max", () => {
    let arr: number[] = [];
    for (let i = 0; i < 10; i++) arr = pushBounded(arr, i, 3);
    expect(arr).toEqual([7, 8, 9]);
  });
});

describe("reduce", () => {
  it("updates sensor + history on sensor events", () => {
    const evt: SensorEvent = {
      type: "sensor",
      data: {
        timestamp: "2026-01-01T00:00:00Z",
        imu_orientation: { x: 0.1, y: 0.2, z: 0 },
        imu_angular_velocity: { x: 0.3, y: 0, z: 0 },
        imu_linear_acceleration: { x: 0, y: 0, z: 9.81 },
        joint_positions: {},
        joint_velocities: {},
        battery_voltage: 24,
        battery_percent: 80,
      },
    };
    const s = reduce(emptyState(), evt);
    expect(s.sensor).toBe(evt.data);
    expect(s.history.orientX).toEqual([0.1]);
    expect(s.history.battery).toEqual([80]);
  });

  it("appends transition log entries with monotonic ids", () => {
    const t1: StateTransitionEvent = {
      type: "state_transition",
      from_state: "IDLE",
      to_state: "STANDING",
      timestamp: "2026-01-01T00:00:00Z",
      reason: "manual",
    };
    const t2: StateTransitionEvent = { ...t1, from_state: "STANDING", to_state: "WALKING" };
    let s = reduce(emptyState(), t1);
    s = reduce(s, t2);
    expect(s.log).toHaveLength(2);
    expect(s.log[0].id).toBe(1);
    expect(s.log[1].id).toBe(2);
    expect(s.lastReason).toBe("manual");
  });

  it("caps log at LOG_LEN", () => {
    let s = emptyState();
    for (let i = 0; i < LOG_LEN + 10; i++) {
      const evt: StateTransitionEvent = {
        type: "state_transition",
        from_state: "IDLE",
        to_state: "STANDING",
        timestamp: "2026-01-01T00:00:00Z",
        reason: `r${i}`,
      };
      s = reduce(s, evt);
    }
    expect(s.log.length).toBe(LOG_LEN);
    expect(s.log[0].kind === "transition" && s.log[0].reason).toBe("r10");
  });

  it("handles AI command and status events", () => {
    const ai: AICommandEvent = {
      type: "ai_command",
      input: "stand",
      command: "stand",
      params: {},
      explanation: "일어선다",
    };
    const status: StatusEvent = {
      type: "status",
      status: {
        state: "STANDING",
        previous_state: "IDLE",
        current_behavior: null,
        last_transition: "2026-01-01T00:00:00Z",
        error: null,
      },
    };
    let s = reduce(emptyState(), ai);
    s = reduce(s, status);
    expect(s.log).toHaveLength(1);
    expect(s.log[0].kind).toBe("ai");
    expect(s.status?.state).toBe("STANDING");
  });
});
