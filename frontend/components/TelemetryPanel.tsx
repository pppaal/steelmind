"use client";

import Sparkline from "./Sparkline";
import type { ConnectionState, SensorHistory } from "@/lib/useRobotSocket";
import { STATE_COLORS, type RobotStatus, type SensorData } from "@/lib/types";

interface Props {
  connection: ConnectionState;
  status: RobotStatus | null;
  sensor: SensorData | null;
  history: SensorHistory;
  lastReason: string | null;
}

function fmt(n: number | undefined, digits = 3): string {
  if (n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 text-xs">
      <span className="text-zinc-500">{label}</span>
      <span className="font-mono text-zinc-100">{value}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">{title}</div>
      <div className="space-y-1 rounded-md border border-zinc-800 bg-zinc-900/60 p-3">{children}</div>
    </div>
  );
}

export default function TelemetryPanel({ connection, status, sensor, history, lastReason }: Props) {
  const state = status?.state ?? "IDLE";
  const stateColor = STATE_COLORS[state];

  return (
    <aside className="flex h-full w-80 shrink-0 flex-col gap-4 overflow-y-auto border-l border-zinc-800 bg-zinc-950/80 p-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-200">Telemetry</h2>
          <span
            className={`flex items-center gap-1.5 text-[10px] uppercase tracking-wider ${
              connection === "open"
                ? "text-emerald-400"
                : connection === "connecting"
                  ? "text-amber-400"
                  : "text-rose-400"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                connection === "open"
                  ? "bg-emerald-400"
                  : connection === "connecting"
                    ? "bg-amber-400 animate-pulse"
                    : "bg-rose-400"
              }`}
            />
            {connection}
          </span>
        </div>
        <div
          className="flex items-center gap-2 rounded-md border px-3 py-2"
          style={{ borderColor: stateColor, backgroundColor: `${stateColor}1a` }}
        >
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: stateColor }} />
          <span className="font-mono text-sm font-semibold" style={{ color: stateColor }}>
            {state}
          </span>
          {status?.current_behavior ? (
            <span className="ml-auto text-[10px] text-zinc-400">
              behavior: <span className="text-zinc-200">{status.current_behavior}</span>
            </span>
          ) : null}
        </div>
      </div>

      <Section title="Status">
        <Row label="state" value={state} />
        <Row label="previous" value={status?.previous_state ?? "—"} />
        <Row label="behavior" value={status?.current_behavior ?? "—"} />
        <Row label="reason" value={lastReason ?? "—"} />
        <Row label="error" value={status?.error ?? "—"} />
      </Section>

      <Section title="IMU — Orientation X">
        <Row label="current" value={fmt(sensor?.imu_orientation.x)} />
        <Sparkline data={history.orientX} domain={[-0.6, 0.6]} zeroLine color="#38bdf8" fill="rgba(56,189,248,0.15)" />
      </Section>

      <Section title="IMU — Orientation Y">
        <Row label="current" value={fmt(sensor?.imu_orientation.y)} />
        <Sparkline data={history.orientY} domain={[-0.6, 0.6]} zeroLine color="#a78bfa" fill="rgba(167,139,250,0.15)" />
      </Section>

      <Section title="IMU — Angular Velocity X">
        <Row label="current" value={fmt(sensor?.imu_angular_velocity.x)} />
        <Sparkline data={history.angVelX} domain={[-0.6, 0.6]} zeroLine color="#f472b6" fill="rgba(244,114,182,0.15)" />
      </Section>

      <Section title="IMU — Linear Acceleration">
        <Row label="x" value={fmt(sensor?.imu_linear_acceleration.x)} />
        <Row label="y" value={fmt(sensor?.imu_linear_acceleration.y)} />
        <Row label="z" value={fmt(sensor?.imu_linear_acceleration.z)} />
      </Section>

      <Section title="Joint Positions (rad)">
        {sensor?.joint_positions
          ? Object.entries(sensor.joint_positions).map(([k, v]) => <Row key={k} label={k} value={fmt(v)} />)
          : <div className="text-xs text-zinc-500">—</div>}
      </Section>

      {sensor?.joint_efforts && Object.keys(sensor.joint_efforts).length > 0 && (
        <Section title="Joint Load (effort)">
          {(() => {
            const efforts = sensor.joint_efforts!;
            const peak = Math.max(0.001, ...Object.values(efforts).filter(Number.isFinite));
            return Object.entries(efforts).map(([k, v]) => {
              const frac = Math.max(0, Math.min(1, (Number.isFinite(v) ? v : 0) / peak));
              return (
                <div key={k} className="flex items-center gap-2 py-0.5">
                  <span className="w-28 shrink-0 truncate text-xs text-zinc-400">{k}</span>
                  <div className="h-1.5 flex-1 rounded bg-zinc-800">
                    <div
                      className="h-full rounded bg-amber-400"
                      style={{ width: `${frac * 100}%` }}
                    />
                  </div>
                  <span className="w-12 shrink-0 text-right font-mono text-[10px] text-zinc-500">
                    {fmt(v, 2)}
                  </span>
                </div>
              );
            });
          })()}
        </Section>
      )}

      <Section title="Battery">
        <Row label="voltage" value={`${fmt(sensor?.battery_voltage, 2)} V`} />
        <Row label="percent" value={`${fmt(sensor?.battery_percent, 1)} %`} />
        <Sparkline data={history.battery} domain={[0, 100]} color="#34d399" fill="rgba(52,211,153,0.15)" />
      </Section>
    </aside>
  );
}
