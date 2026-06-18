"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import RoutineBuilder from "./RoutineBuilder";
import { authHeaders } from "@/lib/api";
import type { RoutineProgress } from "@/lib/useRobotSocket";

interface Props {
  apiBase: string;
  jointNames: string[];
  routine?: RoutineProgress | null;
  // Server-side latched e-stop, derived from the live status stream. Lets the
  // panel reflect (and react to) an e-stop triggered from anywhere — another
  // operator, the watchdog, a script — not just this client's button.
  serverEstopped?: boolean;
}

interface KeyframesResponse {
  keyframes: Record<string, Record<string, number>>;
}

const JOG_STEP = 0.15; // rad, ~8.6° per step — under the server's MAX_JOG_RAD
const JOG_REPEAT_MS = 150; // hold-to-jog cadence (~7 Hz)

export default function HardwarePanel({
  apiBase,
  jointNames,
  routine,
  serverEstopped = false,
}: Props) {
  const [keyframes, setKeyframes] = useState<string[]>([]);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [estopped, setEstopped] = useState(false);
  // Kinematics: hasChain is discovered by probing /fk (400 when no chain).
  const [hasChain, setHasChain] = useState(false);
  const [reachTarget, setReachTarget] = useState({ x: "0.15", y: "0.10" });
  const [fk, setFk] = useState<{ x: number; y: number } | null>(null);
  const [workspace, setWorkspace] = useState<{
    base: [number, number];
    inner_radius: number;
    outer_radius: number;
  } | null>(null);
  const [routines, setRoutines] = useState<string[]>([]);
  const [behaviors, setBehaviors] = useState<string[]>([]);
  const [aiEnabled, setAiEnabled] = useState(false);

  const post = useCallback(
    async (path: string, body?: unknown, method = "POST") => {
      setError(null);
      const res = await fetch(`${apiBase}${path}`, {
        method,
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(detail.detail ?? `HTTP ${res.status}`);
      }
      return res.json();
    },
    [apiBase],
  );

  const refreshKeyframes = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/keyframes`, { headers: authHeaders() });
      if (!res.ok) return;
      const data = (await res.json()) as KeyframesResponse;
      setKeyframes(Object.keys(data.keyframes));
    } catch {
      /* ignore */
    }
  }, [apiBase]);

  const refreshFk = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/fk`, { headers: authHeaders() });
      const d = res.ok ? await res.json() : null;
      if (d && typeof d.x === "number" && typeof d.y === "number") {
        setHasChain(true);
        setFk({ x: d.x, y: d.y });
      } else {
        setHasChain(false);
      }
    } catch {
      setHasChain(false);
    }
  }, [apiBase]);

  const refreshWorkspace = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/workspace`, { headers: authHeaders() });
      if (!res.ok) {
        setWorkspace(null);
        return;
      }
      const d = await res.json();
      if (
        Array.isArray(d.base) &&
        typeof d.inner_radius === "number" &&
        typeof d.outer_radius === "number"
      ) {
        setWorkspace({ base: [d.base[0], d.base[1]], inner_radius: d.inner_radius, outer_radius: d.outer_radius });
      }
    } catch {
      setWorkspace(null);
    }
  }, [apiBase]);

  const refreshRoutines = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/routines`, { headers: authHeaders() });
      if (!res.ok) return;
      const data = (await res.json()) as { routines: Record<string, unknown[]> };
      setRoutines(Object.keys(data.routines));
    } catch {
      /* ignore */
    }
  }, [apiBase]);

  useEffect(() => {
    void refreshKeyframes();
    void refreshFk();
    void refreshWorkspace();
    void refreshRoutines();
    fetch(`${apiBase}/behaviors`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.behaviors) setBehaviors(d.behaviors.map((b: { name: string }) => b.name));
      })
      .catch(() => {});
    fetch(`${apiBase}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setAiEnabled(Boolean(d?.ai_enabled)))
      .catch(() => {});
  }, [apiBase, refreshKeyframes, refreshFk, refreshWorkspace, refreshRoutines]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Press-and-hold continuous jog. We bypass the busy gate (which would
  // disable the button after the first call) and instead guard against
  // overlapping requests with an in-flight ref, so holding the button
  // streams jog steps at JOG_REPEAT_MS without piling up requests.
  const holdRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jogInFlight = useRef(false);

  const jogOnce = useCallback(
    async (joint: string, dir: 1 | -1) => {
      if (jogInFlight.current) return;
      jogInFlight.current = true;
      try {
        const res = await fetch(`${apiBase}/jog`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ joint, delta: dir * JOG_STEP }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(body.detail ?? `HTTP ${res.status}`);
        }
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        jogInFlight.current = false;
      }
    },
    [apiBase],
  );

  const stopHold = useCallback(() => {
    if (holdRef.current) {
      clearInterval(holdRef.current);
      holdRef.current = null;
    }
  }, []);

  const startHold = useCallback(
    (joint: string, dir: 1 | -1) => {
      if (estopped) return;
      stopHold();
      void jogOnce(joint, dir); // immediate first step
      holdRef.current = setInterval(() => void jogOnce(joint, dir), JOG_REPEAT_MS);
    },
    [estopped, jogOnce, stopHold],
  );

  // Stop any active hold when the component unmounts.
  useEffect(() => stopHold, [stopHold]);

  // Reconcile with server-side e-stop. If an e-stop latches anywhere (watchdog,
  // another operator, a script) we must reflect it locally AND immediately drop
  // any in-progress jog hold — otherwise the interval keeps streaming jog steps
  // the server will reject, and the UI lies about the robot being live.
  useEffect(() => {
    if (serverEstopped) {
      stopHold();
      setEstopped(true);
    } else {
      setEstopped(false);
    }
  }, [serverEstopped, stopHold]);

  const estop = () =>
    run(async () => {
      stopHold(); // drop any in-progress hold before cutting torque
      await post("/estop");
      setEstopped(true);
    });

  const clearEstop = () =>
    run(async () => {
      await post("/estop/clear");
      setEstopped(false);
    });

  const exportRoutine = (name: string) =>
    run(async () => {
      const res = await fetch(`${apiBase}/routines/${encodeURIComponent(name)}`, {
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`export failed: ${res.status}`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `routine-${name}.json`;
      a.click();
      URL.revokeObjectURL(url);
    });

  const importRoutine = (file: File) =>
    run(async () => {
      const text = await file.text();
      let parsed: { name?: string; steps?: unknown };
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new Error("not valid JSON");
      }
      if (!parsed.steps || !Array.isArray(parsed.steps)) throw new Error("missing steps[]");
      // Default the name from the file's name field or the filename.
      const name = (parsed.name || file.name.replace(/\.json$/, "").replace(/^routine-/, "")).trim();
      if (!name) throw new Error("could not derive a routine name");
      await post(`/routines/${encodeURIComponent(name)}`, { steps: parsed.steps }, "PUT");
      await refreshRoutines();
    });

  const recordKeyframe = () =>
    run(async () => {
      const name = newName.trim();
      if (!name) return;
      await post(`/keyframes/${encodeURIComponent(name)}`);
      setNewName("");
      await refreshKeyframes();
    });

  const deleteKeyframe = (name: string) =>
    run(async () => {
      await post(`/keyframes/${encodeURIComponent(name)}`, undefined, "DELETE");
      await refreshKeyframes();
    });

  const playKeyframes = () =>
    run(() => post("/keyframes/play", { names: keyframes }));

  const doReach = () =>
    run(async () => {
      const x = parseFloat(reachTarget.x);
      const y = parseFloat(reachTarget.y);
      if (Number.isNaN(x) || Number.isNaN(y)) throw new Error("x/y must be numbers");
      const res = (await post("/reach", { x, y })) as { reached: boolean };
      if (!res.reached) setError("target out of reach — moved to closest pose");
      setTimeout(() => void refreshFk(), 600);
    });

  // Client-side reach pre-check against the cached workspace annulus. A fast
  // hint so the operator sees an out-of-range target before sending it; the
  // server's IK stays the authority (it still moves to the closest pose).
  const reachCheck = (() => {
    if (!workspace) return null;
    const x = parseFloat(reachTarget.x);
    const y = parseFloat(reachTarget.y);
    if (Number.isNaN(x) || Number.isNaN(y)) return null;
    const d = Math.hypot(x - workspace.base[0], y - workspace.base[1]);
    const eps = 1e-6;
    if (d > workspace.outer_radius + eps) return { ok: false, msg: "beyond reach" };
    if (d < workspace.inner_radius - eps) return { ok: false, msg: "too close to base" };
    return { ok: true, msg: "" };
  })();

  return (
    <div className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto border-l border-zinc-800 bg-zinc-950/80 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-200">Hardware</h2>
        {busy && <span className="text-[10px] text-zinc-500">working…</span>}
      </div>

      {/* E-STOP — always reachable, big and red */}
      {estopped ? (
        <button
          onClick={clearEstop}
          className="rounded-md border border-amber-500 bg-amber-500/10 px-4 py-3 text-sm font-bold uppercase tracking-wider text-amber-300 transition hover:bg-amber-500/20"
        >
          Clear E-Stop
        </button>
      ) : (
        <button
          onClick={estop}
          className="rounded-md border-2 border-rose-600 bg-rose-600/20 px-4 py-3 text-sm font-bold uppercase tracking-widest text-rose-300 transition hover:bg-rose-600/40"
        >
          ■ E-STOP
        </button>
      )}

      {error && (
        <div className="rounded border border-rose-500/50 bg-rose-950/60 px-2 py-1 font-mono text-[10px] text-rose-300">
          {error}
        </div>
      )}

      {/* Per-joint jog — press and hold for continuous motion */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          Jog ({(JOG_STEP * 57.3).toFixed(0)}° / step · hold to repeat)
        </div>
        <div className="space-y-1 rounded-md border border-zinc-800 bg-zinc-900/60 p-2">
          {jointNames.length === 0 ? (
            <div className="text-[11px] text-zinc-600">no joints</div>
          ) : (
            jointNames.map((j) => {
              const holdProps = (dir: 1 | -1) => ({
                onPointerDown: () => startHold(j, dir),
                onPointerUp: stopHold,
                onPointerLeave: stopHold,
                // Touch fallback (some browsers don't fire pointer events).
                onTouchEnd: stopHold,
                disabled: estopped,
                className:
                  "h-6 w-6 rounded border border-zinc-700 text-xs text-zinc-300 hover:border-sky-500 active:bg-sky-600/30 disabled:opacity-30",
              });
              return (
                <div key={j} className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-[10px] text-zinc-400">{j}</span>
                  <div className="flex shrink-0 gap-1">
                    <button aria-label={`jog ${j} negative`} {...holdProps(-1)}>
                      −
                    </button>
                    <button aria-label={`jog ${j} positive`} {...holdProps(1)}>
                      +
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Reach (IK) — only when the robot config defines a kinematic chain */}
      {hasChain && (
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
            Reach (IK)
          </div>
          <div className="space-y-2 rounded-md border border-zinc-800 bg-zinc-900/60 p-2">
            {fk && (
              <div className="font-mono text-[10px] text-zinc-500">
                tip: ({fk.x.toFixed(3)}, {fk.y.toFixed(3)}) m
              </div>
            )}
            {workspace && (
              <div className="font-mono text-[10px] text-zinc-600">
                reach: {workspace.inner_radius.toFixed(3)}–{workspace.outer_radius.toFixed(3)} m
              </div>
            )}
            <div className="flex items-center gap-1">
              <label className="font-mono text-[10px] text-zinc-500">x</label>
              <input
                value={reachTarget.x}
                onChange={(e) => setReachTarget((t) => ({ ...t, x: e.target.value }))}
                className="w-14 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-1 text-[11px] text-zinc-100 outline-none focus:border-sky-500"
              />
              <label className="font-mono text-[10px] text-zinc-500">y</label>
              <input
                value={reachTarget.y}
                onChange={(e) => setReachTarget((t) => ({ ...t, y: e.target.value }))}
                className="w-14 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-1 text-[11px] text-zinc-100 outline-none focus:border-sky-500"
              />
              <button
                onClick={doReach}
                disabled={busy || estopped || reachCheck?.ok === false}
                className="ml-auto rounded bg-indigo-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
              >
                Reach
              </button>
            </div>
            {reachCheck?.ok === false && (
              <div className="text-[10px] text-amber-400">target {reachCheck.msg}</div>
            )}
          </div>
        </div>
      )}

      {/* Teach & repeat */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          Teach &amp; Repeat
        </div>
        <div className="space-y-2 rounded-md border border-zinc-800 bg-zinc-900/60 p-2">
          <div className="flex gap-1">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="keyframe name"
              className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[11px] text-zinc-100 outline-none focus:border-sky-500"
            />
            <button
              onClick={recordKeyframe}
              disabled={busy || !newName.trim()}
              className="rounded bg-sky-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-sky-500 disabled:opacity-40"
            >
              Record
            </button>
          </div>
          {keyframes.length > 0 && (
            <>
              <div className="max-h-28 space-y-0.5 overflow-y-auto">
                {keyframes.map((k) => (
                  <div key={k} className="flex items-center justify-between">
                    <span className="font-mono text-[10px] text-zinc-300">{k}</span>
                    <button
                      onClick={() => deleteKeyframe(k)}
                      className="text-[10px] text-zinc-500 hover:text-rose-400"
                    >
                      del
                    </button>
                  </div>
                ))}
              </div>
              <button
                onClick={playKeyframes}
                disabled={busy || estopped}
                className="w-full rounded border border-emerald-600 bg-emerald-600/15 px-2 py-1.5 text-[11px] font-semibold text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40"
              >
                ▶ Replay {keyframes.length} pose{keyframes.length > 1 ? "s" : ""}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Routines — saved macros: run existing, build new */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          Routines
        </div>
        {routine && routine.status === "running" && (
          <div className="rounded-md border border-indigo-700 bg-indigo-950/50 px-2 py-1.5">
            <div className="flex items-center justify-between text-[10px]">
              <span className="font-mono text-indigo-300">▶ {routine.name}</span>
              <span className="text-indigo-400">
                {Math.max(0, routine.index + 1)}/{routine.total}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded bg-indigo-900">
              <div
                className="h-full bg-indigo-400 transition-all"
                style={{
                  width: `${routine.total > 0 ? (Math.max(0, routine.index + 1) / routine.total) * 100 : 0}%`,
                }}
              />
            </div>
          </div>
        )}
        {routine && routine.status !== "running" && (
          <div
            className={`rounded-md px-2 py-1 text-[10px] ${
              routine.status === "complete"
                ? "text-emerald-400"
                : routine.status === "cancelled"
                  ? "text-zinc-500"
                  : "text-rose-400"
            }`}
          >
            {routine.name}: {routine.status}
            {routine.detail ? ` — ${routine.detail}` : ""}
          </div>
        )}
        <div className="space-y-2 rounded-md border border-zinc-800 bg-zinc-900/60 p-2">
          {routines.length > 0 &&
            routines.map((r) => (
              <div key={r} className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-[11px] text-zinc-300">{r}</span>
                <div className="flex shrink-0 gap-1">
                  <button
                    onClick={() => exportRoutine(r)}
                    disabled={busy}
                    title="export as JSON"
                    className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400 hover:border-zinc-500 disabled:opacity-40"
                  >
                    ⬇
                  </button>
                  <button
                    onClick={() => run(() => post(`/routines/${encodeURIComponent(r)}/run`))}
                    disabled={busy || estopped}
                    className="rounded border border-indigo-600 px-2 py-0.5 text-[10px] font-semibold text-indigo-300 hover:bg-indigo-600/20 disabled:opacity-40"
                  >
                    ▶ run
                  </button>
                </div>
              </div>
            ))}
          <label className="block cursor-pointer rounded border border-zinc-700 px-2 py-1 text-center text-[11px] text-zinc-400 hover:border-sky-500 hover:text-zinc-200">
            ⬆ import routine
            <input
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void importRoutine(file);
                e.target.value = "";
              }}
            />
          </label>
          <RoutineBuilder
            apiBase={apiBase}
            behaviors={behaviors}
            hasChain={hasChain}
            onSaved={refreshRoutines}
            aiEnabled={aiEnabled}
          />
        </div>
      </div>
    </div>
  );
}
