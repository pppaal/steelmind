"use client";

import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "@/lib/api";

interface Props {
  apiBase: string;
  jointNames: string[];
}

interface KeyframesResponse {
  keyframes: Record<string, Record<string, number>>;
}

const JOG_STEP = 0.15; // rad, ~8.6° per click — under the server's MAX_JOG_RAD

export default function HardwarePanel({ apiBase, jointNames }: Props) {
  const [keyframes, setKeyframes] = useState<string[]>([]);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [estopped, setEstopped] = useState(false);

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

  useEffect(() => {
    void refreshKeyframes();
  }, [refreshKeyframes]);

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

  const jog = (joint: string, dir: 1 | -1) =>
    run(() => post("/jog", { joint, delta: dir * JOG_STEP }));

  const estop = () =>
    run(async () => {
      await post("/estop");
      setEstopped(true);
    });

  const clearEstop = () =>
    run(async () => {
      await post("/estop/clear");
      setEstopped(false);
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

      {/* Per-joint jog */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          Jog ({(JOG_STEP * 57.3).toFixed(0)}° / click)
        </div>
        <div className="space-y-1 rounded-md border border-zinc-800 bg-zinc-900/60 p-2">
          {jointNames.length === 0 ? (
            <div className="text-[11px] text-zinc-600">no joints</div>
          ) : (
            jointNames.map((j) => (
              <div key={j} className="flex items-center justify-between gap-2">
                <span className="truncate font-mono text-[10px] text-zinc-400">{j}</span>
                <div className="flex shrink-0 gap-1">
                  <button
                    onClick={() => jog(j, -1)}
                    disabled={busy || estopped}
                    className="h-6 w-6 rounded border border-zinc-700 text-xs text-zinc-300 hover:border-sky-500 disabled:opacity-30"
                  >
                    −
                  </button>
                  <button
                    onClick={() => jog(j, 1)}
                    disabled={busy || estopped}
                    className="h-6 w-6 rounded border border-zinc-700 text-xs text-zinc-300 hover:border-sky-500 disabled:opacity-30"
                  >
                    +
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

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
    </div>
  );
}
