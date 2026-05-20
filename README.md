# steelmind

A humanoid robot control stack: a FastAPI backend (state machine, behavior
tree, trajectory engine, hardware abstraction layer, Claude-powered natural
language control) and a Next.js + Three.js operator console. Runs against a
software simulator out of the box; swap one env var to drive real Dynamixel
or LeRobot SO-100 servos.

> Scope note: this is the **control / teleoperation layer** — mission
> planning, command translation, trajectory playback, telemetry, and a
> hardware abstraction layer. It is not a real-time whole-body controller.
> The 1 kHz balance/locomotion loop a walking humanoid needs lives below
> this layer; steelmind targets upper-body / arm position control where a
> 20 Hz async loop is sufficient.

## Architecture

```
┌─────────────────────────────────────────┐   /ws    ┌──────────────────────────────┐
│ frontend (Next.js + Three.js)           │ ◄──────► │ backend (FastAPI)            │
│  RobotScene  TelemetryPanel  EventLog    │          │  ConnectionManager (fan-out) │
│  HardwarePanel (jog/estop/teach/reach/   │  HTTP    │  StateMachine (async)        │
│   routines)  CommandBar  AICommandInput  │ ───────► │  Trajectory player           │
└─────────────────────────────────────────┘          │  AICommander → Claude        │
                                                      │  HAL ── mock | dynamixel |   │
                                                      │         lerobot              │
                                                      └──────────────┬───────────────┘
                                                                     ▼ servos
```

* **State machine** — `IDLE / STANDING / WALKING / EXECUTING` with validated
  transitions; subscribers receive `state_transition` events.
* **Hardware abstraction layer** (`backend/hardware/`) — one `RobotHardware`
  interface; `mock` (slewing simulator, default), `dynamixel` (protocol-2
  XL/XM via U2D2), and `lerobot` (SO-100) implementations. Selected by
  `ROBOT_HARDWARE`. The rest of the stack never touches a servo directly.
* **Trajectory engine** (`backend/trajectory.py`) — `hold / linear /
  min_jerk / sinusoid / compose`. Behaviors, keyframe replay, IK reach, and
  routines all play through one trajectory player at `SENSOR_HZ`.
* **Behaviors** (`backend/behaviors.py`) — `demo / wave / squat / patrol /
  dance`, each a real joint trajectory (not a hardcoded sensor sine).
* **Kinematics** (`backend/kinematics.py`) — planar FK + damped-least-squares
  IK with random restarts (numpy-free). Powers `/fk` and `/reach`.
* **AI commander** (`backend/ai_commander.py`) — `claude-haiku-4-5` with
  **forced tool use**, prompt-cache reuse, per-session memory, and a
  validator-driven self-repair loop. Translates language to commands
  (`/ai-command`) and to whole routines (`/ai-routine`).
* **Safety** (`backend/safety.py`) — joint-limit clamping, velocity slewing,
  and a watchdog that E-stops if the read loop stalls. `/estop` latches.

## Control modes

| Mode            | Entry point                          | What it does                              |
|-----------------|--------------------------------------|-------------------------------------------|
| State command   | `/command`, CommandBar               | stand / walk / idle / stop                |
| Behavior        | `/command` execute, CommandBar       | play a named trajectory (wave, dance…)    |
| Natural language| `/ai-command`, AICommandInput        | Claude → command/plan                     |
| AI routine      | `/ai-routine`, RoutineBuilder        | Claude → saved multi-step macro           |
| Coordinate      | `/reach`, HardwarePanel              | IK to an (x, y) target                     |
| Teach & repeat  | `/keyframes*`, HardwarePanel         | record poses by hand, replay smoothly     |
| Routine macro   | `/routines*`, RoutineBuilder         | sequence command/behavior/wait/reach/keyframes |
| Manual          | `/jog`, HardwarePanel                | per-joint nudge                            |
| Emergency       | `/estop`, HardwarePanel              | latching torque cut + force IDLE          |

## Project layout

```
steelmind/
├── backend/
│   ├── main.py            FastAPI app + all routes + trajectory player
│   ├── state_machine.py   async StateMachine + transition events
│   ├── behavior_tree.py   minimal async BT engine
│   ├── behaviors.py       BEHAVIORS registry (trajectory factories)
│   ├── trajectory.py      hold/linear/min_jerk/sinusoid/compose
│   ├── kinematics.py      planar FK + damped-least-squares IK
│   ├── keyframes.py       teach-and-repeat pose store
│   ├── routines.py        routine macro store
│   ├── ai_commander.py    Claude: command + routine composition
│   ├── plan_validator.py  dry-run AI plans against the transition table
│   ├── hardware/
│   │   ├── base.py        RobotHardware ABC + dataclasses
│   │   ├── mock.py        slewing software simulator (default)
│   │   ├── dynamixel.py   protocol-2 driver (lazy dynamixel-sdk)
│   │   └── lerobot.py     SO-100 driver (lazy lerobot)
│   ├── robot_config.py    JSON/YAML joint + chain loader
│   ├── configs/           sim_humanoid · torso_humanoid · so100_arm
│   ├── calibration.py     per-joint offset persistence
│   ├── safety.py          clamp / slew / watchdog
│   ├── auth.py            viewer/operator/admin token roles
│   ├── rate_limit.py      token bucket
│   ├── journal.py / journal_postgres.py / journal_base.py   event log
│   ├── metrics (in main)  Prometheus counters + histogram
│   ├── middleware.py      request-id + body size limit
│   ├── logging_setup.py   JSON / text logging
│   ├── tracing.py         optional OpenTelemetry
│   ├── secrets.py         env-or-file resolver
│   ├── models.py          Pydantic wire models
│   ├── tests/             pytest suite (188 tests)
│   └── Dockerfile
├── frontend/
│   ├── app/page.tsx       operator console layout
│   ├── components/        RobotScene, TelemetryPanel, EventLog, CommandBar,
│   │                      AICommandInput, HardwarePanel, RoutineBuilder,
│   │                      KeyboardShortcuts, Sparkline
│   ├── lib/               useRobotSocket, socketReducer, api, session,
│   │                      types, openapi.d.ts (generated)
│   └── Dockerfile
├── scripts/hardware_bringup.py   interactive servo bring-up + calibration
├── loadtest/k6.js                throughput + latency load test
├── docker-compose.yml
├── Makefile
├── requirements*.txt      base / dev / postgres / otel
└── pyproject.toml         ruff + pytest config
```

## Running

### Local (simulator — zero config)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > backend/.env   # optional, for AI features
uvicorn backend.main:app --reload

# Frontend (new terminal)
cd frontend && npm install && npm run dev      # http://localhost:3000
```

### Docker

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env    # optional
docker compose up --build
# frontend → http://localhost:3000, backend → http://localhost:8000
```

### Against real hardware

```bash
pip install dynamixel-sdk          # or: pip install lerobot
# 1) validate wiring + zero the joints (talks to the bus directly)
python scripts/hardware_bringup.py --config backend/configs/so100_arm.json \
    --backend lerobot --port /dev/ttyUSB0
# 2) run the server against the bus
ROBOT_HARDWARE=lerobot ROBOT_HARDWARE_PORT=/dev/ttyUSB0 \
    ROBOT_CONFIG=backend/configs/so100_arm.json \
    uvicorn backend.main:app
```

The Dynamixel/LeRobot drivers are structured and unit-tested (conversion,
packing, estop) with a mocked SDK, but have not been run against physical
silicon — validate with `hardware_bringup.py` (torque-low, E-stop in hand)
before relying on them.

## API

| Method | Path                     | Role     | Description                                   |
|--------|--------------------------|----------|-----------------------------------------------|
| GET    | `/health`                | —        | state, clients, ai/auth flags, readiness      |
| GET    | `/livez` `/readyz`       | —        | k8s liveness / readiness probes               |
| GET    | `/metrics`               | —        | Prometheus counters + AI latency histogram    |
| GET    | `/status`                | —        | current `RobotStatus`                         |
| GET    | `/behaviors`             | —        | available behaviors                           |
| POST   | `/command`               | operator | stand / walk / idle / stop / execute          |
| POST   | `/ai-command`            | operator | language → command/plan, executes             |
| POST   | `/ai-routine`            | operator | language → saved routine                      |
| POST   | `/ai-reset`              | admin    | clear AI conversation memory                  |
| POST   | `/estop` `/estop/clear`  | op/admin | latching emergency stop / reset               |
| POST   | `/jog`                   | operator | nudge one joint (bounded)                     |
| GET/POST | `/calibration`         | view/admin | read / set joint offsets                    |
| GET    | `/fk`                    | viewer   | end-effector position (needs a chain)         |
| POST   | `/reach`                 | operator | IK to (x, y), moves there                     |
| GET/POST/DELETE | `/keyframes*`   | view/op  | teach-and-repeat poses                        |
| GET/PUT/DELETE/run | `/routines*` | view/op  | routine macros + run                          |
| GET    | `/journal/*`             | viewer   | transition / AI-command history               |
| WS     | `/ws`                    | operator | telemetry + command channel                   |

Full request/response schemas are generated into `frontend/lib/openapi.d.ts`
(via `npm run gen:api`); CI fails if it drifts from the live spec.

### WebSocket frames (server → client)

* `{"type":"sensor","data":{...}}` — joints + IMU + battery at `SENSOR_HZ`
* `{"type":"status","status":{...}}` — on connect & after each transition
* `{"type":"state_transition", ...}` / `{"type":"ai_command", ...}`
* `{"type":"routine_started|routine_step|routine_complete|routine_cancelled|routine_failed", ...}`
* `{"type":"ping"}` — heartbeat; clients reply `{"type":"pong"}`

Clients send commands as `{"type":"command","payload":{"command":"...","params":{}}}`.
When `API_TOKEN*` is set, connect with `/ws?token=<token>`.

## Testing

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q           # 188 backend tests
cd frontend && npm run typecheck && npm test && npm run build   # 32 frontend tests
```

CI (`.github/workflows/ci.yml`) runs ruff + pytest, frontend tsc + vitest +
build, both Docker image builds, a live backend integration smoke, and an
OpenAPI drift check.

## Environment variables

Secrets accept an `*_FILE` variant pointing at a file path (Docker / k8s
secret convention); the file is read with trailing whitespace stripped.

| Variable                       | Where    | Default                    | Notes                                          |
|--------------------------------|----------|----------------------------|------------------------------------------------|
| `ANTHROPIC_API_KEY`            | backend  | unset                      | required for `/ai-command`, `/ai-routine`      |
| `API_TOKEN`                    | backend  | unset                      | legacy single-token mode → operator role       |
| `API_TOKEN_VIEWER/OPERATOR/ADMIN` | backend | unset                  | comma-sep token lists per role                 |
| `ROBOT_HARDWARE`               | backend  | `mock`                     | `mock` / `dynamixel` / `lerobot`               |
| `ROBOT_HARDWARE_PORT`          | backend  | `/dev/ttyUSB0`             | serial port for real drivers                   |
| `ROBOT_HARDWARE_BAUD`          | backend  | `1000000`                  | dynamixel baud rate                            |
| `ROBOT_CONFIG`                 | backend  | `backend/configs/sim_humanoid.json` | joint + chain config              |
| `CALIBRATION_FILE`             | backend  | `calibration.json`         | per-joint offset store                         |
| `KEYFRAMES_FILE`               | backend  | `keyframes.json`           | taught pose store                              |
| `ROUTINES_FILE`                | backend  | `routines.json`            | routine macro store                            |
| `MAX_JOG_RAD`                  | backend  | `0.35`                     | max single `/jog` step                         |
| `HARDWARE_WATCHDOG_SEC`        | backend  | `2.0`                      | read-loop stall → E-stop                       |
| `KEYFRAME_SEGMENT_SEC`         | backend  | `1.5`                      | min-jerk segment between poses                 |
| `SENSOR_HZ`                    | backend  | `20`                       | sensor + trajectory tick rate                  |
| `AI_TIMEOUT_SEC`               | backend  | `20`                       | per-request anthropic timeout                  |
| `AI_RATE_PER_SEC` / `AI_RATE_BURST` | backend | `0.5` / `3`            | AI endpoint token bucket                        |
| `MAX_REQUEST_BYTES`            | backend  | `65536`                    | HTTP body cap → 413                            |
| `WS_HEARTBEAT_SEC` / `_TIMEOUT_SEC` | backend | `20` / `60`            | server ping cadence / idle eviction            |
| `JOURNAL_BACKEND`              | backend  | `sqlite`                   | `sqlite` or `postgres`                         |
| `JOURNAL_DB` / `JOURNAL_DSN`   | backend  | `steelmind.db` / unset     | sqlite path / postgres URL                     |
| `JOURNAL_KEEP_TRANSITIONS` / `_AI` | backend | `5000` / `1000`         | retention caps                                 |
| `JOURNAL_PRUNE_INTERVAL_SEC`   | backend  | `60`                       | background prune cycle                         |
| `CORS_ORIGINS`                 | backend  | `*`                        | comma-sep; wildcard disables credentials       |
| `LOG_FORMAT`                   | backend  | tty → text, else json      | force with `json` or `text`                    |
| `OTEL_EXPORTER_OTLP_ENDPOINT`  | backend  | unset                      | enables tracing; needs `requirements-otel.txt` |
| `NEXT_PUBLIC_WS_URL`           | frontend | `ws://localhost:8000/ws`   | HTTP base auto-derived; token via localStorage |

## Auth roles

| Role     | Capabilities                                                       |
|----------|-------------------------------------------------------------------|
| viewer   | read journals, `/fk`, list keyframes/routines                      |
| operator | viewer + all motion (command/ai/reach/jog/keyframes/routines/ws)   |
| admin    | operator + `/ai-reset`, `/calibration`, `/estop/clear`            |

When no `API_TOKEN*` is set, auth is bypassed (single-user dev/demo). A bare
`API_TOKEN` grants the operator role (backwards compatible).

## Optional integrations

* **Postgres journal**: `pip install -r requirements-postgres.txt`, set
  `JOURNAL_BACKEND=postgres` and `JOURNAL_DSN=postgresql://...` so multiple
  backend replicas share event history.
* **OpenTelemetry**: `pip install -r requirements-otel.txt`, set
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318`.
* **Load testing**: `make loadtest` (`k6 run loadtest/k6.js`).

## Hardware bring-up

The BOM and wiring guidance for a Dynamixel upper body or a LeRobot SO-100
arm, plus the `scripts/hardware_bringup.py` flow (ping → read → zero → jog →
sweep), are the path from simulator to metal. Start with one lightly-loaded
joint, keep a hand on the power switch, and use `"invert": true` in the
config if a joint runs backwards.
