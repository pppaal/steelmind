"use client";

import { useEffect, useState } from "react";
import { STATE_COLORS, type RobotState } from "@/lib/types";

interface Props {
  state: RobotState;
  disabled: boolean;
  onCommand: (command: string, params?: Record<string, unknown>) => void;
  apiBase: string;
}

const COMMANDS: { label: string; command: string; tone: RobotState }[] = [
  { label: "Idle", command: "idle", tone: "IDLE" },
  { label: "Stand", command: "stand", tone: "STANDING" },
  { label: "Walk", command: "walk", tone: "WALKING" },
];

interface Behavior {
  name: string;
  description: string;
}

export default function CommandBar({ state, disabled, onCommand, apiBase }: Props) {
  const [behaviors, setBehaviors] = useState<Behavior[]>([{ name: "demo", description: "" }]);
  const [selected, setSelected] = useState<string>("demo");

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/behaviors`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.behaviors?.length) {
          setBehaviors(data.behaviors as Behavior[]);
          setSelected(data.behaviors[0].name as string);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  const exeColor = STATE_COLORS.EXECUTING;
  const exeActive = state === "EXECUTING";

  return (
    <div className="flex flex-wrap items-center justify-center gap-3 border-t border-zinc-800 bg-zinc-950/80 px-4 py-3">
      {COMMANDS.map((c) => {
        const active = state === c.tone;
        const color = STATE_COLORS[c.tone];
        return (
          <button
            key={c.command}
            disabled={disabled}
            onClick={() => onCommand(c.command)}
            className="min-w-[110px] rounded-md border px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              borderColor: color,
              color: active ? "#0a0f1c" : color,
              backgroundColor: active ? color : "transparent",
            }}
          >
            {c.label}
          </button>
        );
      })}

      <div className="flex items-center overflow-hidden rounded-md border" style={{ borderColor: exeColor }}>
        <button
          disabled={disabled}
          onClick={() => onCommand("execute", { behavior: selected })}
          title={behaviors.find((b) => b.name === selected)?.description ?? ""}
          className="min-w-[110px] px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            color: exeActive ? "#0a0f1c" : exeColor,
            backgroundColor: exeActive ? exeColor : "transparent",
          }}
        >
          Execute
        </button>
        <select
          value={selected}
          disabled={disabled}
          onChange={(e) => setSelected(e.target.value)}
          className="border-l bg-zinc-900 px-2 py-2 text-xs font-mono text-zinc-100 outline-none disabled:opacity-40"
          style={{ borderColor: exeColor }}
        >
          {behaviors.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
