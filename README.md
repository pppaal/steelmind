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

| Variable               | Where      | Default                    | Notes                              |
|------------------------|------------|----------------------------|------------------------------------|
| `ANTHROPIC_API_KEY`    | backend    | unset                      | required for `/ai-command`         |
| `SENSOR_HZ`            | backend    | `20`                       | sensor broadcast rate              |
| `NEXT_PUBLIC_WS_URL`   | frontend   | `ws://localhost:8000/ws`   | also used to derive HTTP base      |
