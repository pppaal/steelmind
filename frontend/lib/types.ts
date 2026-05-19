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

export interface AICommandEvent {
  type: "ai_command";
  input: string;
  command: string;
  params: Record<string, unknown>;
  explanation: string;
  step_count?: number;
  repaired?: boolean;
}

export interface PlanCompletedEvent {
  type: "plan_completed";
  step_count: number;
}

export interface PlanStepFailedEvent {
  type: "plan_step_failed";
  command: string;
  detail: string;
}

export type ServerEvent =
  | StateTransitionEvent
  | SensorEvent
  | StatusEvent
  | BehaviorEvent
  | AICommandEvent
  | PlanCompletedEvent
  | PlanStepFailedEvent
  | { type: "pong" }
  | { type: "error"; detail: string }
  | { ok: boolean; message?: string; status: RobotStatus };

export interface AIPlanStep {
  command: string;
  params: Record<string, unknown>;
  executed: boolean;
  detail: string | null;
}

export interface AICommandResponse {
  explanation: string;
  steps: AIPlanStep[];
  fully_executed: boolean;
}

export const STATE_COLORS: Record<RobotState, string> = {
  IDLE: "#3b82f6",
  STANDING: "#22c55e",
  WALKING: "#eab308",
  EXECUTING: "#ef4444",
};
