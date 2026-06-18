"use client";

import { useEffect, useRef, useState } from "react";
import { authHeaders } from "@/lib/api";

interface Props {
  apiBase: string;
  // Poll cadence in ms (~5 fps default). Snapshots are pulled via fetch (not a
  // bare <img src>) so the auth header rides along when API_TOKEN is set.
  intervalMs?: number;
}

export default function CameraPanel({ apiBase, intervalMs = 200 }: Props) {
  const [available, setAvailable] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/camera/info`, { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled) setAvailable(Boolean(d?.available));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch(`${apiBase}/camera/snapshot`, { headers: authHeaders() });
        if (!r.ok || cancelled) return;
        const blob = await r.blob();
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = url;
        setSrc(url);
      } catch {
        /* transient; next tick retries */
      }
    };
    void tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [available, apiBase, intervalMs]);

  if (!available) return null;

  return (
    <div className="pointer-events-none absolute right-4 top-4 overflow-hidden rounded-md border border-zinc-700 bg-zinc-950/80 shadow-lg">
      <div className="flex items-center gap-1.5 px-2 py-1">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-500" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          Camera
        </span>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {src && <img src={src} alt="robot camera" className="block w-48" />}
    </div>
  );
}
