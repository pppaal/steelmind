"use client";

import { useCallback, useEffect, useState } from "react";
import { authHeaders } from "@/lib/api";

interface Props {
  apiBase: string;
}

/** Session recorder controls: start/stop capturing the broadcast event
 * timeline and download it as JSON for audit / time-travel debugging. */
export default function RecordingPanel({ apiBase }: Props) {
  const [active, setActive] = useState(false);
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/recording`, { headers: authHeaders() });
      if (!r.ok) return;
      const d = await r.json();
      setActive(Boolean(d.active));
      setCount(Number(d.count ?? 0));
    } catch {
      /* ignore */
    }
  }, [apiBase]);

  useEffect(() => {
    void refresh();
    const id = setInterval(refresh, 1000);
    return () => clearInterval(id);
  }, [refresh]);

  const toggle = async () => {
    setBusy(true);
    try {
      const path = active ? "/recording/stop" : "/recording/start";
      const r = await fetch(`${apiBase}${path}`, { method: "POST", headers: authHeaders() });
      if (r.ok) {
        const d = await r.json();
        setActive(Boolean(d.active));
        setCount(Number(d.count ?? 0));
      }
    } catch {
      /* ignore */
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    try {
      const r = await fetch(`${apiBase}/recording/export`, { headers: authHeaders() });
      if (!r.ok) return;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `steelmind-session-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="pointer-events-auto absolute left-4 top-14 flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/85 px-2.5 py-1.5 backdrop-blur">
      <button
        type="button"
        onClick={() => void toggle()}
        disabled={busy}
        className={`flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-wider transition disabled:opacity-40 ${
          active ? "bg-rose-600 text-white hover:bg-rose-500" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${active ? "animate-pulse bg-white" : "bg-rose-500"}`} />
        {active ? "Recording" : "Record"}
      </button>
      <span className="font-mono text-[10px] text-zinc-500">{count}</span>
      <button
        type="button"
        onClick={() => void download()}
        disabled={count === 0}
        className="rounded border border-zinc-700 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-400 transition hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-40"
      >
        Download
      </button>
    </div>
  );
}
