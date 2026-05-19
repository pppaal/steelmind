"use client";

import { useEffect } from "react";

interface Props {
  enabled: boolean;
  onCommand: (command: string, params?: Record<string, unknown>) => void;
}

const BINDINGS: Record<string, { command: string; params?: Record<string, unknown> }> = {
  "1": { command: "idle" },
  "2": { command: "stand" },
  "3": { command: "walk" },
  "4": { command: "execute", params: { behavior: "demo" } },
};

export default function KeyboardShortcuts({ enabled, onCommand }: Props) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (target?.isContentEditable) return;
      const binding = BINDINGS[e.key];
      if (!binding) return;
      e.preventDefault();
      onCommand(binding.command, binding.params);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, onCommand]);

  return (
    <div className="pointer-events-none absolute right-4 top-4 rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-2 font-mono text-[10px] text-zinc-500">
      <div className="font-semibold uppercase tracking-wider text-zinc-400">Keys</div>
      <div>
        <kbd className="text-zinc-300">1</kbd> idle ·{" "}
        <kbd className="text-zinc-300">2</kbd> stand ·{" "}
        <kbd className="text-zinc-300">3</kbd> walk ·{" "}
        <kbd className="text-zinc-300">4</kbd> execute
      </div>
    </div>
  );
}
