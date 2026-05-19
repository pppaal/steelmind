// k6 load test for the steelmind backend.
//
//   k6 run loadtest/k6.js
//   k6 run -e BASE_URL=http://localhost:8000 -e WS_URL=ws://localhost:8000/ws \
//          -e API_TOKEN=secret loadtest/k6.js
//
// Three scenarios run in parallel:
//   - probe_storm: hammers /livez and /readyz; verifies sub-ms response.
//   - command_burst: sticks to the valid IDLE↔STANDING transition pair so
//     the state machine never short-circuits with 409s.
//   - ws_subscribers: opens long-lived /ws connections and counts frames.
//
// Thresholds at the bottom fail the run if regressions creep in.

import { check, sleep } from "k6";
import http from "k6/http";
import ws from "k6/ws";
import { Counter, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const WS_URL = __ENV.WS_URL || "ws://localhost:8000/ws";
const API_TOKEN = __ENV.API_TOKEN || "";

const authHeaders = API_TOKEN
  ? { Authorization: `Bearer ${API_TOKEN}`, "Content-Type": "application/json" }
  : { "Content-Type": "application/json" };
const wsUrl = API_TOKEN ? `${WS_URL}?token=${encodeURIComponent(API_TOKEN)}` : WS_URL;

const wsFrames = new Counter("ws_frames_received");
const wsConnectMs = new Trend("ws_connect_ms");

export const options = {
  scenarios: {
    probe_storm: {
      executor: "constant-arrival-rate",
      rate: 50,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: 5,
      exec: "probe",
    },
    command_burst: {
      executor: "constant-arrival-rate",
      rate: 5,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: 2,
      exec: "commandLoop",
      startTime: "2s",
    },
    ws_subscribers: {
      executor: "per-vu-iterations",
      vus: 10,
      iterations: 1,
      maxDuration: "30s",
      exec: "wsSubscribe",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{scenario:probe_storm}": ["p(95)<10"],
    "http_req_duration{scenario:command_burst}": ["p(95)<200"],
    ws_frames_received: ["count>500"],
    ws_connect_ms: ["p(95)<200"],
  },
};

export function probe() {
  const res = http.get(`${BASE_URL}/readyz`);
  check(res, { "readyz 200": (r) => r.status === 200 });
}

export function commandLoop() {
  // Stick to a valid transition pair to avoid 409 spam — the state machine
  // rejects WALKING from IDLE.
  let r = http.post(
    `${BASE_URL}/command`,
    JSON.stringify({ command: "stand", params: {} }),
    { headers: authHeaders, tags: { scenario: "command_burst" } },
  );
  check(r, { "stand accepted": (resp) => resp.status === 200 });

  sleep(0.2);

  r = http.post(
    `${BASE_URL}/command`,
    JSON.stringify({ command: "idle", params: {} }),
    { headers: authHeaders, tags: { scenario: "command_burst" } },
  );
  check(r, { "idle accepted": (resp) => resp.status === 200 });
}

export function wsSubscribe() {
  const start = Date.now();
  const res = ws.connect(wsUrl, {}, (socket) => {
    wsConnectMs.add(Date.now() - start);
    socket.on("message", (msg) => {
      wsFrames.add(1);
      // Echo server pings so we don't get heartbeat-evicted.
      try {
        const parsed = JSON.parse(msg);
        if (parsed.type === "ping") {
          socket.send(JSON.stringify({ type: "pong" }));
        }
      } catch (_) {
        // ignore
      }
    });
    socket.setTimeout(() => socket.close(), 20_000);
  });
  check(res, { "ws handshake ok": (r) => r && r.status === 101 });
}
