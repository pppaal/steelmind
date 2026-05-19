"use client";

import { useEffect, useRef, useState } from "react";
import { deriveApiBase } from "@/lib/api";
import type { AICommandResponse } from "@/lib/types";

interface Bubble {
  id: number;
  text: string;
  steps: { command: string; behavior?: string }[];
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
    const ttl = Math.min(8000, 2500 + b.steps.length * 800);
    timerRef.current = setTimeout(() => setBubble(null), ttl);
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
        steps: data.steps.map((s) => ({
          command: s.command,
          behavior: typeof s.params?.behavior === "string" ? (s.params.behavior as string) : undefined,
        })),
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
                : "border-sky-500/60 bg-sky-950/90 text-sky-100"
            }`}
          >
            {error ? (
              <span className="font-mono text-xs">{error}</span>
            ) : (
              <div className="space-y-1.5">
                <div>{bubble?.text}</div>
                <div className="flex flex-wrap items-center gap-1">
                  {bubble?.steps.map((s, i) => (
                    <span key={i} className="flex items-center gap-1">
                      {i > 0 && <span className="text-zinc-500">→</span>}
                      <span className="rounded bg-zinc-800/70 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider">
                        {s.command}
                        {s.behavior ? `:${s.behavior}` : ""}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div
              className={`absolute -bottom-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 border-b border-r ${
                error ? "border-rose-500/60 bg-rose-950/90" : "border-sky-500/60 bg-sky-950/90"
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
