"use client";

import { STATE_COLORS, type RobotState } from "@/lib/types";

interface Props {
  state: RobotState;
  disabled: boolean;
  onCommand: (command: string, params?: Record<string, unknown>) => void;
}

const COMMANDS: { label: string; command: string; tone: RobotState }[] = [
  { label: "Idle", command: "idle", tone: "IDLE" },
  { label: "Stand", command: "stand", tone: "STANDING" },
  { label: "Walk", command: "walk", tone: "WALKING" },
  { label: "Execute", command: "execute", tone: "EXECUTING" },
];

export default function CommandBar({ state, disabled, onCommand }: Props) {
  return (
    <div className="flex items-center justify-center gap-3 border-t border-zinc-800 bg-zinc-950/80 px-4 py-3">
      {COMMANDS.map((c) => {
        const active = state === c.tone;
        const color = STATE_COLORS[c.tone];
        return (
          <button
            key={c.command}
            disabled={disabled}
            onClick={() => onCommand(c.command, c.command === "execute" ? { behavior: "demo" } : undefined)}
            className="group relative min-w-[110px] rounded-md border px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
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
    </div>
  );
}
