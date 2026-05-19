import type { RobotState, RobotStatus, SensorData, ServerEvent } from "./types";

export const HISTORY_LEN = 60;
export const LOG_LEN = 50;

export interface SensorHistory {
  orientX: number[];
  orientY: number[];
  angVelX: number[];
  battery: number[];
}

export type LogEntry =
  | { kind: "transition"; id: number; t: string; from: RobotState; to: RobotState; reason: string | null }
  | { kind: "ai"; id: number; t: string; input: string; command: string; explanation: string };

export interface SocketState {
  status: RobotStatus | null;
  sensor: SensorData | null;
  history: SensorHistory;
  log: LogEntry[];
  lastReason: string | null;
  nextId: number;
}

export function emptyHistory(): SensorHistory {
  return { orientX: [], orientY: [], angVelX: [], battery: [] };
}

export function emptyState(): SocketState {
  return {
    status: null,
    sensor: null,
    history: emptyHistory(),
    log: [],
    lastReason: null,
    nextId: 0,
  };
}

export function pushBounded(arr: number[], v: number, max = HISTORY_LEN): number[] {
  const next = arr.length >= max ? arr.slice(arr.length - max + 1) : arr.slice();
  next.push(v);
  return next;
}

export function reduce(state: SocketState, evt: ServerEvent): SocketState {
  if (!("type" in evt)) {
    if ("status" in evt) return { ...state, status: evt.status };
    return state;
  }
  switch (evt.type) {
    case "sensor": {
      const d = evt.data;
      return {
        ...state,
        sensor: d,
        history: {
          orientX: pushBounded(state.history.orientX, d.imu_orientation.x),
          orientY: pushBounded(state.history.orientY, d.imu_orientation.y),
          angVelX: pushBounded(state.history.angVelX, d.imu_angular_velocity.x),
          battery: pushBounded(state.history.battery, d.battery_percent),
        },
      };
    }
    case "status":
      return { ...state, status: evt.status };
    case "state_transition": {
      const log = state.log.slice(-(LOG_LEN - 1));
      log.push({
        kind: "transition",
        id: state.nextId + 1,
        t: evt.timestamp,
        from: evt.from_state,
        to: evt.to_state,
        reason: evt.reason,
      });
      return { ...state, lastReason: evt.reason, log, nextId: state.nextId + 1 };
    }
    case "ai_command": {
      const log = state.log.slice(-(LOG_LEN - 1));
      log.push({
        kind: "ai",
        id: state.nextId + 1,
        t: new Date().toISOString(),
        input: evt.input,
        command: evt.command,
        explanation: evt.explanation,
      });
      return { ...state, log, nextId: state.nextId + 1 };
    }
    default:
      return state;
  }
}
