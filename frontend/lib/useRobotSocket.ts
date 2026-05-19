"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiToken } from "./api";
import {
  emptyState,
  reduce,
  type LogEntry,
  type SensorHistory,
  type SocketState,
} from "./socketReducer";
import type { RobotStatus, SensorData, ServerEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

export type { LogEntry, SensorHistory } from "./socketReducer";

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

function wsUrlWithToken(): string {
  const token = getApiToken();
  if (!token) return WS_URL;
  // Browsers can't set Authorization headers on WS upgrade, so the server
  // accepts ?token=... as the auth channel. encodeURIComponent guards
  // against token bytes that would corrupt the query string.
  const sep = WS_URL.includes("?") ? "&" : "?";
  return `${WS_URL}${sep}token=${encodeURIComponent(token)}`;
}

export function useRobotSocket(): RobotSocket {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [state, setState] = useState<SocketState>(emptyState);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    setConnection("connecting");
    const ws = new WebSocket(wsUrlWithToken());
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
      // Server-driven heartbeat: echo any ping so the server's idle-eviction
      // sweep sees us as live. The reducer ignores ping/pong frames.
      if ("type" in parsed && parsed.type === "ping") {
        try {
          ws.send(JSON.stringify({ type: "pong" }));
        } catch {
          /* socket closing; ignore */
        }
        return;
      }
      setState((s) => reduce(s, parsed));
    };
  }, []);

  useEffect(() => {
    connect();
    // Reconnect when the API token changes in another tab (storage event
    // only fires cross-tab) OR when this tab calls setApiToken (we dispatch
    // a synthetic storage event there). Without this, a user who pastes a
    // new token sees their existing socket keep using the old one until
    // the next natural reconnect.
    const onStorage = (e: StorageEvent) => {
      if (e.key === "steelmind_api_token") {
        wsRef.current?.close();
      }
    };
    window.addEventListener("storage", onStorage);
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      window.removeEventListener("storage", onStorage);
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

  return {
    connection,
    status: state.status,
    sensor: state.sensor,
    history: state.history,
    log: state.log,
    lastReason: state.lastReason,
    sendCommand,
  };
}
