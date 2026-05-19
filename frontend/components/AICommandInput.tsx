"use client";

import { useEffect, useRef, useState } from "react";
import type { AICommandResponse } from "@/lib/types";

function deriveApiBase(): string {
  const ws = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
  try {
    const url = new URL(ws);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return "http://localhost:8000";
  }
}

interface Bubble {
  id: number;
  text: string;
  command: string;
  executed: boolean;
  detail: string | null;
}

export default function AICommandInput() {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const apiBase = useRef<string>(deriveApiBase());

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const showBubble = (b: Bubble) => {
    setBubble(b);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setBubble(null), 3000);
  };

  const submit = async () => {
    const value = text.trim();
    if (!value || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase.current}/ai-command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as AICommandResponse;
      showBubble({
        id: Date.now(),
        text: data.explanation,
        command: data.command,
        executed: data.executed,
        detail: data.detail,
      });
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <div className="relative flex w-full max-w-2xl items-center gap-2">
      {(bubble || error) && (
        <div
          className={`pointer-events-none absolute -top-3 left-0 right-0 -translate-y-full transition-opacity duration-300 ${
            bubble || error ? "opacity-100" : "opacity-0"
          }`}
        >
          <div
            className={`relative mx-auto max-w-xl rounded-lg border px-4 py-2 text-sm shadow-lg ${
              error
                ? "border-rose-500/60 bg-rose-950/90 text-rose-200"
                : bubble?.executed
                  ? "border-sky-500/60 bg-sky-950/90 text-sky-100"
                  : "border-amber-500/60 bg-amber-950/90 text-amber-100"
            }`}
          >
            {error ? (
              <span className="font-mono text-xs">{error}</span>
            ) : (
              <>
                <span className="mr-2 rounded bg-zinc-800/70 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider">
                  {bubble?.command}
                </span>
                <span>{bubble?.text}</span>
                {bubble && !bubble.executed && bubble.detail ? (
                  <span className="ml-2 text-[10px] text-zinc-400">({bubble.detail})</span>
                ) : null}
              </>
            )}
            <div
              className={`absolute -bottom-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 border-b border-r ${
                error
                  ? "border-rose-500/60 bg-rose-950/90"
                  : bubble?.executed
                    ? "border-sky-500/60 bg-sky-950/90"
                    : "border-amber-500/60 bg-amber-950/90"
              }`}
            />
          </div>
        </div>
      )}

      <div className="flex w-full items-center gap-2 rounded-md border border-zinc-700 bg-zinc-900/80 px-3 py-2 focus-within:border-sky-500">
        <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">AI</span>
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder="자연어로 명령하세요 — 예: 일어서서 앞으로 걸어"
          className="flex-1 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none"
          disabled={loading}
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={loading || !text.trim()}
          className="flex items-center gap-2 rounded-md bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? (
            <>
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
              <span>thinking…</span>
            </>
          ) : (
            <span>Send</span>
          )}
        </button>
      </div>
    </div>
  );
}
