"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RobotStatus, SensorData, ServerEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

export interface RobotSocket {
  connection: ConnectionState;
  status: RobotStatus | null;
  sensor: SensorData | null;
  lastReason: string | null;
  sendCommand: (command: string, params?: Record<string, unknown>) => void;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";

export function useRobotSocket(): RobotSocket {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [status, setStatus] = useState<RobotStatus | null>(null);
  const [sensor, setSensor] = useState<SensorData | null>(null);
  const [lastReason, setLastReason] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
        if (parsed.type === "sensor") setSensor(parsed.data);
        else if (parsed.type === "status") setStatus(parsed.status);
        else if (parsed.type === "state_transition") setLastReason(parsed.reason);
      } else if ("status" in parsed) {
        setStatus(parsed.status);
      }
    };
  }, []);

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

  return { connection, status, sensor, lastReason, sendCommand };
}
