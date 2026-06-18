"use client";

import { useEffect, useRef } from "react";
import type { LogEntry } from "@/lib/useRobotSocket";
import { STATE_COLORS } from "@/lib/types";

interface Props {
  entries: LogEntry[];
}

function shortTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString(undefined, { hour12: false });
  } catch {
    return iso;
  }
}

export default function EventLog({ entries }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  // Stay pinned to the newest event only while the user is already at the
  // bottom. If they scroll up to read history, don't yank them back down.
  const stickRef = useRef(true);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  useEffect(() => {
    if (stickRef.current && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [entries.length]);

  return (
    <div className="pointer-events-auto absolute bottom-4 left-4 w-96 rounded-md border border-zinc-800 bg-zinc-950/85 backdrop-blur">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          Event Log
        </span>
        <span className="font-mono text-[10px] text-zinc-600">{entries.length}</span>
      </div>
      <div
        ref={ref}
        onScroll={onScroll}
        className="h-32 overflow-y-auto px-3 py-2 font-mono text-[11px]"
      >
        {entries.length === 0 ? (
          <div className="text-zinc-600">waiting for events…</div>
        ) : (
          entries.map((e) => (
            <div key={e.id} className="flex gap-2 py-0.5">
              <span className="text-zinc-600">{shortTime(e.t)}</span>
              {e.kind === "transition" ? (
                <span className="flex items-center gap-1">
                  <span style={{ color: STATE_COLORS[e.from] }}>{e.from}</span>
                  <span className="text-zinc-500">→</span>
                  <span style={{ color: STATE_COLORS[e.to] }}>{e.to}</span>
                  {e.reason ? <span className="text-zinc-500">· {e.reason}</span> : null}
                </span>
              ) : (
                <span className="flex flex-1 items-baseline gap-1.5">
                  <span className="rounded bg-sky-900/60 px-1 py-0.5 text-[9px] uppercase text-sky-300">
                    AI
                  </span>
                  <span className="text-zinc-300">{e.command}</span>
                  <span className="truncate text-zinc-500">{e.explanation}</span>
                </span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
