# steelmind

Realtime humanoid robot simulator: FastAPI backend with a state machine and
behavior-tree engine, Next.js + Three.js frontend, and Claude-powered natural
language command translation.

## Architecture

```
┌──────────────────────────────────────────┐         ┌──────────────────────────┐
│ frontend (Next.js + Three.js)            │  /ws    │ backend (FastAPI)        │
│  ┌────────────┐  ┌────────────────────┐  │ ◄─────► │  ConnectionManager       │
│  │ RobotScene │  │ TelemetryPanel     │  │         │   ├─ sensor loop @20Hz   │
│  │ OrbitCtrl  │  │  + IMU sparklines  │  │ HTTP    │   └─ transition fan-out  │
│  │ skeleton   │  │ EventLog           │  │ ──────► │  StateMachine (async)    │
│  └────────────┘  └────────────────────┘  │         │  BehaviorTree (Seq/Sel)  │
│  CommandBar   AICommandInput             │ ──────► │  AICommander → Claude    │
└──────────────────────────────────────────┘         └──────────────────────────┘
```

* **State machine** — `IDLE / STANDING / WALKING / EXECUTING` with validated
  transitions; subscribers receive `state_transition` events.
* **Behavior tree** — minimal async engine (`Sequence`, `Selector`, `Parallel`,
  `Action`, `Condition`). Behaviors live in `backend/behaviors.py`:
  `demo`, `wave`, `squat`, `patrol`, `dance`.
* **Sensor simulation** — `simulate_sensor` produces IMU + joint positions
  whose shape depends on `(state, current_behavior)`, so the 3D model
  visibly reacts to whatever the robot is doing.
* **AI commander** — `claude-haiku-4-5` with **forced tool use** so the
  output is always a valid `{command, params, explanation}` payload, and
  with `cache_control: ephemeral` on the system prompt for prompt-cache
  reuse across calls.

## Project layout

```
steelmind/
├── backend/
│   ├── main.py            FastAPI app, /ws, /command, /ai-command, /behaviors
│   ├── state_machine.py   async StateMachine + transition events
│   ├── behavior_tree.py   minimal async BT engine
│   ├── behaviors.py       BEHAVIORS registry + descriptions
│   ├── ai_commander.py    Claude integration (forced tool use, prompt cache)
│   ├── models.py          Pydantic models
│   ├── tests/             pytest suite
│   └── Dockerfile
├── frontend/
│   ├── app/page.tsx       Top-level layout
│   ├── components/
│   │   ├── RobotScene.tsx     Three.js skeleton + OrbitControls + shadows
│   │   ├── TelemetryPanel.tsx Status + IMU sparklines + battery
│   │   ├── EventLog.tsx       Recent transitions + AI commands
│   │   ├── CommandBar.tsx     stand / walk / idle / execute(behavior)
│   │   ├── AICommandInput.tsx Natural language input
│   │   └── Sparkline.tsx
│   ├── lib/
│   │   ├── useRobotSocket.ts  WS client + sensor history buffer
│   │   ├── types.ts
│   │   └── api.ts
│   └── Dockerfile
├── docker-compose.yml
├── requirements.txt / requirements-dev.txt
├── pyproject.toml         pytest config
└── README.md
```

## Running

### Local

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > backend/.env   # optional, for /ai-command
uvicorn backend.main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev      # http://localhost:3000
```

### Docker

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
docker compose up --build
# → frontend at http://localhost:3000, backend at http://localhost:8000
```

## API

| Method | Path           | Description                                                  |
|--------|----------------|--------------------------------------------------------------|
| GET    | `/health`      | Liveness + current state + connected clients                 |
| GET    | `/status`      | Current `RobotStatus`                                        |
| GET    | `/behaviors`   | Available behavior names + descriptions                      |
| POST   | `/command`     | `{command, params}` — stand / walk / idle / stop / execute   |
| POST   | `/ai-command`  | `{text}` — Claude translates → executes → broadcasts         |
| WS     | `/ws`          | Streams `sensor`, `status`, `state_transition`, `ai_command` |

### WebSocket frames

* `{"type":"sensor","data":{...}}` — 20 Hz (configurable via `SENSOR_HZ`)
* `{"type":"status","status":{...}}` — on connect & after each transition
* `{"type":"state_transition","from_state":"...","to_state":"...","reason":"..."}`
* `{"type":"ai_command","input":"...","command":"...","explanation":"..."}`

Clients can send `{"type":"command","payload":{"command":"...","params":{}}}`
through the same socket — useful for one-shot UIs that don't want to hold
HTTP connections.

## Testing

```bash
pip install -r requirements-dev.txt
pytest                       # 24 tests covering state machine, BT, HTTP routes
cd frontend && npm run typecheck && npm run build
```

## Environment variables

Most secrets accept an `*_FILE` variant pointing at a file path (Docker /
k8s secret convention). The file's contents are read with trailing
whitespace stripped.

| Variable                       | Where    | Default                    | Notes                                          |
|--------------------------------|----------|----------------------------|------------------------------------------------|
| `ANTHROPIC_API_KEY`            | backend  | unset                      | required for `/ai-command`                     |
| `API_TOKEN`                    | backend  | unset                      | legacy single-token mode → operator role       |
| `API_TOKEN_VIEWER`             | backend  | unset                      | comma-sep; can read `/journal/*`               |
| `API_TOKEN_OPERATOR`           | backend  | unset                      | comma-sep; can issue commands, run AI          |
| `API_TOKEN_ADMIN`              | backend  | unset                      | comma-sep; everything incl. `/ai-reset`        |
| `SENSOR_HZ`                    | backend  | `20`                       | sensor broadcast rate                          |
| `AI_TIMEOUT_SEC`               | backend  | `20`                       | per-request anthropic timeout                  |
| `AI_RATE_PER_SEC`              | backend  | `0.5`                      | sustained req/s through `/ai-command`          |
| `AI_RATE_BURST`                | backend  | `3`                        | token bucket burst                             |
| `MAX_REQUEST_BYTES`            | backend  | `65536`                    | HTTP body cap → 413                            |
| `WS_HEARTBEAT_SEC`             | backend  | `20`                       | server-side ping cadence                       |
| `WS_HEARTBEAT_TIMEOUT_SEC`     | backend  | `60`                       | idle ws eviction threshold                     |
| `JOURNAL_BACKEND`              | backend  | `sqlite`                   | `sqlite` or `postgres`                         |
| `JOURNAL_DB`                   | backend  | `steelmind.db`             | sqlite file path                               |
| `JOURNAL_DSN`                  | backend  | unset                      | postgres URL when backend=postgres             |
| `JOURNAL_KEEP_TRANSITIONS`     | backend  | `5000`                     | retention cap                                  |
| `JOURNAL_KEEP_AI`              | backend  | `1000`                     | retention cap                                  |
| `JOURNAL_PRUNE_INTERVAL_SEC`   | backend  | `60`                       | background prune cycle                         |
| `CORS_ORIGINS`                 | backend  | `*`                        | comma-sep; wildcard disables credentials       |
| `LOG_FORMAT`                   | backend  | tty → text, else json      | force with `json` or `text`                    |
| `OTEL_EXPORTER_OTLP_ENDPOINT`  | backend  | unset                      | enables tracing; needs `requirements-otel.txt` |
| `OTEL_SERVICE_NAME`            | backend  | `steelmind`                | OTel service.name resource attr                |
| `NEXT_PUBLIC_WS_URL`           | frontend | `ws://localhost:8000/ws`   | HTTP base is auto-derived                      |

## Auth roles

| Role     | Endpoints                                                    |
|----------|--------------------------------------------------------------|
| viewer   | `/journal/transitions`, `/journal/ai-commands`               |
| operator | viewer + `/command`, `/ai-command`, `/ws` (with `?token=`)   |
| admin    | operator + `/ai-reset`                                       |

When no `API_TOKEN*` is set, auth is bypassed (single-user dev/demo). With
`API_TOKEN` alone, that token grants the operator role — same behavior as
before role-based auth landed.

## Optional integrations

* **Postgres journal**: `pip install -r requirements-postgres.txt`,
  set `JOURNAL_BACKEND=postgres` and `JOURNAL_DSN=postgresql://...`.
* **OpenTelemetry**: `pip install -r requirements-otel.txt`, set
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318` and traces flow
  for every HTTP request (and the Anthropic httpx calls inside them).
* **Load testing**: `k6 run loadtest/k6.js` (with `BASE_URL`, `WS_URL`,
  `API_TOKEN` env). Runs probe storm, command burst, ws subscriber
  scenarios with throughput + latency thresholds.
