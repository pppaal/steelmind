"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RobotState, RobotStatus, SensorData, ServerEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

export type LogEntry =
  | { kind: "transition"; id: number; t: string; from: RobotState; to: RobotState; reason: string | null }
  | { kind: "ai"; id: number; t: string; input: string; command: string; explanation: string };

export interface SensorHistory {
  orientX: number[];
  orientY: number[];
  angVelX: number[];
  battery: number[];
}

const HISTORY_LEN = 60;

export interface RobotSocket {
  connection: ConnectionState;
  status: RobotStatus | null;
  sensor: SensorData | null;
  history: SensorHistory;
  log: LogEntry[];
  lastReason: string | null;
  sendCommand: (command: string, params?: Record<string, unknown>) => void;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";

function emptyHistory(): SensorHistory {
  return { orientX: [], orientY: [], angVelX: [], battery: [] };
}

function pushBounded(arr: number[], v: number): number[] {
  const next = arr.length >= HISTORY_LEN ? arr.slice(arr.length - HISTORY_LEN + 1) : arr.slice();
  next.push(v);
  return next;
}

export function useRobotSocket(): RobotSocket {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [status, setStatus] = useState<RobotStatus | null>(null);
  const [sensor, setSensor] = useState<SensorData | null>(null);
  const [history, setHistory] = useState<SensorHistory>(emptyHistory);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [lastReason, setLastReason] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idRef = useRef(0);

  const appendLog = useCallback((entry: LogEntry) => {
    setLog((prev) => {
      const next = prev.slice(-49);
      next.push(entry);
      return next;
    });
  }, []);

  const connect = useCallback(() => {
    setConnection("connecting");
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnection("open");
    ws.onclose = () => {
      setConnection("closed");
      reconnectRef.current = setTimeout(connect, 1500);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => {
      let parsed: ServerEvent;
      try {
        parsed = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }
      if ("type" in parsed) {
        if (parsed.type === "sensor") {
          const d = parsed.data;
          setSensor(d);
          setHistory((h) => ({
            orientX: pushBounded(h.orientX, d.imu_orientation.x),
            orientY: pushBounded(h.orientY, d.imu_orientation.y),
            angVelX: pushBounded(h.angVelX, d.imu_angular_velocity.x),
            battery: pushBounded(h.battery, d.battery_percent),
          }));
        } else if (parsed.type === "status") {
          setStatus(parsed.status);
        } else if (parsed.type === "state_transition") {
          setLastReason(parsed.reason);
          appendLog({
            kind: "transition",
            id: ++idRef.current,
            t: parsed.timestamp,
            from: parsed.from_state,
            to: parsed.to_state,
            reason: parsed.reason,
          });
        } else if (parsed.type === "ai_command") {
          appendLog({
            kind: "ai",
            id: ++idRef.current,
            t: new Date().toISOString(),
            input: parsed.input,
            command: parsed.command,
            explanation: parsed.explanation,
          });
        }
      } else if ("status" in parsed) {
        setStatus(parsed.status);
      }
    };
  }, [appendLog]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendCommand = useCallback(
    (command: string, params: Record<string, unknown> = {}) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "command", payload: { command, params } }));
    },
    [],
  );

  return { connection, status, sensor, history, log, lastReason, sendCommand };
}
