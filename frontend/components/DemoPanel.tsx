"use client";

import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "@/lib/api";

interface Props {
  apiBase: string;
}

/** Demonstration capture for imitation learning: record an episode against a
 * task label, mark it success/failure, and download the dataset (LeRobot-style
 * JSON). */
export default function DemoPanel({ apiBase }: Props) {
  const [active, setActive] = useState(false);
  const [episodes, setEpisodes] = useState(0);
  const [frames, setFrames] = useState(0);
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/demos`, { headers: authHeaders() });
      if (!r.ok) return;
      const d = await r.json();
      setActive(Boolean(d.active));
      setEpisodes(Number(d.episodes ?? 0));
      setFrames(Number(d.current_frames ?? 0));
    } catch {
      /* ignore */
    }
  }, [apiBase]);

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 1000);
    return () => clearInterval(id);
  }, [refresh]);

  const post = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      const r = await fetch(`${apiBase}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (r.ok) {
        const d = await r.json();
        setActive(Boolean(d.active));
        setEpisodes(Number(d.episodes ?? episodes));
      }
    } catch {
      /* ignore */
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    try {
      const r = await fetch(`${apiBase}/demos/export`, { headers: authHeaders() });
      if (!r.ok) return;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `steelmind-demos-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="pointer-events-auto absolute left-4 top-24 flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/85 px-2.5 py-1.5 backdrop-blur">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Demo</span>
      {active ? (
        <>
          <span className="flex items-center gap-1 text-[10px] text-rose-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-500" />
            {frames}
          </span>
          <button
            type="button"
            onClick={() => void post("/demos/stop", { success: true })}
            disabled={busy}
            className="rounded bg-emerald-600 px-2 py-1 text-[10px] font-semibold uppercase text-white hover:bg-emerald-500 disabled:opacity-40"
          >
            ✓ success
          </button>
          <button
            type="button"
            onClick={() => void post("/demos/stop", { success: false })}
            disabled={busy}
            className="rounded bg-rose-700 px-2 py-1 text-[10px] font-semibold uppercase text-white hover:bg-rose-600 disabled:opacity-40"
          >
            ✗ fail
          </button>
        </>
      ) : (
        <>
          <input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="task"
            className="w-24 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-1 text-[11px] text-zinc-100 outline-none focus:border-sky-500"
          />
          <button
            type="button"
            onClick={() => void post("/demos/start", { task })}
            disabled={busy}
            className="rounded bg-zinc-800 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-300 hover:bg-zinc-700 disabled:opacity-40"
          >
            ● Record
          </button>
        </>
      )}
      <span className="font-mono text-[10px] text-zinc-500">{episodes} ep</span>
      <button
        type="button"
        onClick={() => void download()}
        disabled={episodes === 0}
        className="rounded border border-zinc-700 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-400 transition hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-40"
      >
        Download
      </button>
    </div>
  );
}
