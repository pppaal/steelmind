"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getApiToken } from "./api";
import {
  emptyState,
  reduce,
  type LogEntry,
  type RoutineProgress,
  type SensorHistory,
  type SocketState,
} from "./socketReducer";
import type { RobotStatus, SensorData, ServerEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

export type { LogEntry, RoutineProgress, SensorHistory } from "./socketReducer";

export interface RobotSocket {
  connection: ConnectionState;
  status: RobotStatus | null;
  sensor: SensorData | null;
  history: SensorHistory;
  log: LogEntry[];
  lastReason: string | null;
  routine: RoutineProgress | null;
  sendCommand: (command: string, params?: Record<string, unknown>) => void;
  sendDeadman: () => void;
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

    // Guard every handler with an identity check: if wsRef no longer points at
    // this socket, it's been superseded (token change / StrictMode remount) or
    // the hook unmounted. Without this, a closing old socket would setState on
    // an unmounted component and schedule a reconnect that leaks a live socket.
    ws.onopen = () => {
      if (wsRef.current === ws) setConnection("open");
    };
    ws.onclose = () => {
      if (wsRef.current !== ws) return;
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
      // Null the ref first so the socket's onclose identity check bails out
      // instead of scheduling a reconnect after teardown.
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
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

  // Deadman / hold-to-enable ping. The caller sends these repeatedly while the
  // operator holds the enable control; the server keeps motion armed only as
  // long as they keep arriving.
  const sendDeadman = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "deadman" }));
  }, []);

  return {
    connection,
    status: state.status,
    sensor: state.sensor,
    history: state.history,
    log: state.log,
    lastReason: state.lastReason,
    routine: state.routine,
    sendCommand,
    sendDeadman,
  };
}
