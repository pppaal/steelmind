"use client";

import { useState } from "react";
import { authHeaders } from "@/lib/api";

type Step =
  | { type: "command"; command: string }
  | { type: "behavior"; behavior: string }
  | { type: "wait"; seconds: number }
  | { type: "reach"; x: number; y: number };

interface Props {
  apiBase: string;
  behaviors: string[];
  hasChain: boolean;
  onSaved: () => void;
}

const COMMANDS = ["stand", "walk", "idle", "stop"];

function stepLabel(s: Step): string {
  switch (s.type) {
    case "command":
      return `command: ${s.command}`;
    case "behavior":
      return `behavior: ${s.behavior}`;
    case "wait":
      return `wait: ${s.seconds}s`;
    case "reach":
      return `reach: (${s.x}, ${s.y})`;
  }
}

export default function RoutineBuilder({ apiBase, behaviors, hasChain, onSaved }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [stepType, setStepType] = useState<Step["type"]>("command");
  // Per-type draft inputs.
  const [cmd, setCmd] = useState("stand");
  const [beh, setBeh] = useState(behaviors[0] ?? "demo");
  const [secs, setSecs] = useState("1");
  const [reach, setReach] = useState({ x: "0.15", y: "0.10" });
  const [error, setError] = useState<string | null>(null);

  const addStep = () => {
    setError(null);
    if (stepType === "command") setSteps((s) => [...s, { type: "command", command: cmd }]);
    else if (stepType === "behavior") setSteps((s) => [...s, { type: "behavior", behavior: beh }]);
    else if (stepType === "wait") {
      const n = parseFloat(secs);
      if (Number.isNaN(n) || n < 0) return setError("wait seconds must be ≥ 0");
      setSteps((s) => [...s, { type: "wait", seconds: n }]);
    } else if (stepType === "reach") {
      const x = parseFloat(reach.x);
      const y = parseFloat(reach.y);
      if (Number.isNaN(x) || Number.isNaN(y)) return setError("reach x/y must be numbers");
      setSteps((s) => [...s, { type: "reach", x, y }]);
    }
  };

  const removeStep = (i: number) => setSteps((s) => s.filter((_, idx) => idx !== i));

  const save = async () => {
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) return setError("name required");
    if (steps.length === 0) return setError("add at least one step");
    try {
      const res = await fetch(`${apiBase}/routines/${encodeURIComponent(trimmed)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ steps }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setName("");
      setSteps([]);
      setOpen(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-400 hover:border-sky-500 hover:text-zinc-200"
      >
        + new routine
      </button>
    );
  }

  const inputCls =
    "min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-1 text-[11px] text-zinc-100 outline-none focus:border-sky-500";

  return (
    <div className="space-y-2 rounded-md border border-sky-800 bg-zinc-900/60 p-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="routine name"
        className={inputCls}
      />

      {steps.length > 0 && (
        <ol className="space-y-0.5">
          {steps.map((s, i) => (
            <li key={i} className="flex items-center justify-between font-mono text-[10px] text-zinc-300">
              <span>
                {i + 1}. {stepLabel(s)}
              </span>
              <button onClick={() => removeStep(i)} className="text-zinc-500 hover:text-rose-400">
                ✕
              </button>
            </li>
          ))}
        </ol>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <select
          aria-label="step type"
          value={stepType}
          onChange={(e) => setStepType(e.target.value as Step["type"])}
          className="rounded border border-zinc-700 bg-zinc-950 px-1 py-1 text-[11px] text-zinc-100"
        >
          <option value="command">command</option>
          <option value="behavior">behavior</option>
          <option value="wait">wait</option>
          {hasChain && <option value="reach">reach</option>}
        </select>

        {stepType === "command" && (
          <select aria-label="command" value={cmd} onChange={(e) => setCmd(e.target.value)} className={inputCls}>
            {COMMANDS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        )}
        {stepType === "behavior" && (
          <select aria-label="behavior" value={beh} onChange={(e) => setBeh(e.target.value)} className={inputCls}>
            {behaviors.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        )}
        {stepType === "wait" && (
          <input
            aria-label="seconds"
            value={secs}
            onChange={(e) => setSecs(e.target.value)}
            className={inputCls}
            placeholder="seconds"
          />
        )}
        {stepType === "reach" && (
          <>
            <input aria-label="x" value={reach.x} onChange={(e) => setReach((r) => ({ ...r, x: e.target.value }))} className="w-12 rounded border border-zinc-700 bg-zinc-950 px-1 py-1 text-[11px] text-zinc-100" />
            <input aria-label="y" value={reach.y} onChange={(e) => setReach((r) => ({ ...r, y: e.target.value }))} className="w-12 rounded border border-zinc-700 bg-zinc-950 px-1 py-1 text-[11px] text-zinc-100" />
          </>
        )}

        <button
          onClick={addStep}
          className="rounded bg-zinc-700 px-2 py-1 text-[11px] font-semibold text-zinc-100 hover:bg-zinc-600"
        >
          add
        </button>
      </div>

      {error && <div className="font-mono text-[10px] text-rose-400">{error}</div>}

      <div className="flex gap-1">
        <button
          onClick={save}
          className="flex-1 rounded bg-sky-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-sky-500"
        >
          Save
        </button>
        <button
          onClick={() => {
            setOpen(false);
            setSteps([]);
            setName("");
            setError(null);
          }}
          className="rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-400 hover:text-zinc-200"
        >
          cancel
        </button>
      </div>
    </div>
  );
}
