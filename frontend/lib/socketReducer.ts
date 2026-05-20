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

export interface RoutineProgress {
  name: string;
  index: number; // current step (0-based); -1 before the first step runs
  total: number;
  status: "running" | "complete" | "cancelled" | "failed";
  detail?: string;
}

export interface SocketState {
  status: RobotStatus | null;
  sensor: SensorData | null;
  history: SensorHistory;
  log: LogEntry[];
  lastReason: string | null;
  routine: RoutineProgress | null;
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
    routine: null,
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
    case "routine_started":
      return {
        ...state,
        routine: { name: evt.name, index: -1, total: evt.steps, status: "running" },
      };
    case "routine_step":
      // Only advance the routine we think is running (ignore stale events).
      if (!state.routine || state.routine.name !== evt.name) return state;
      return { ...state, routine: { ...state.routine, index: evt.index } };
    case "routine_complete":
    case "routine_cancelled":
    case "routine_failed": {
      if (!state.routine || state.routine.name !== evt.name) return state;
      const status =
        evt.type === "routine_complete"
          ? "complete"
          : evt.type === "routine_cancelled"
            ? "cancelled"
            : "failed";
      return { ...state, routine: { ...state.routine, status, detail: evt.detail } };
    }
    default:
      return state;
  }
}
