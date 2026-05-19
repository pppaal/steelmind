export type RobotState = "IDLE" | "WALKING" | "STANDING" | "EXECUTING";

export interface Vector3 {
  x: number;
  y: number;
  z: number;
}

export interface RobotStatus {
  state: RobotState;
  previous_state: RobotState | null;
  current_behavior: string | null;
  last_transition: string;
  error: string | null;
}

export interface SensorData {
  timestamp: string;
  imu_orientation: Vector3;
  imu_angular_velocity: Vector3;
  imu_linear_acceleration: Vector3;
  joint_positions: Record<string, number>;
  joint_velocities: Record<string, number>;
  battery_voltage: number;
  battery_percent: number;
}

export interface StateTransitionEvent {
  type: "state_transition";
  from_state: RobotState;
  to_state: RobotState;
  timestamp: string;
  reason: string | null;
}

export interface SensorEvent {
  type: "sensor";
  data: SensorData;
}

export interface StatusEvent {
  type: "status";
  status: RobotStatus;
}

export interface BehaviorEvent {
  type: "behavior";
  name: string;
  status: "started" | "running" | "succeeded" | "failed";
  detail: string | null;
}

export type ServerEvent =
  | StateTransitionEvent
  | SensorEvent
  | StatusEvent
  | BehaviorEvent
  | { type: "pong" }
  | { type: "error"; detail: string }
  | { ok: boolean; message?: string; status: RobotStatus };

export const STATE_COLORS: Record<RobotState, string> = {
  IDLE: "#3b82f6",
  STANDING: "#22c55e",
  WALKING: "#eab308",
  EXECUTING: "#ef4444",
};
