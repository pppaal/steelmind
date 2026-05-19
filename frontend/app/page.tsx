"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import AICommandInput from "@/components/AICommandInput";
import CommandBar from "@/components/CommandBar";
import EventLog from "@/components/EventLog";
import TelemetryPanel from "@/components/TelemetryPanel";
import { deriveApiBase } from "@/lib/api";
import { useRobotSocket } from "@/lib/useRobotSocket";

const RobotScene = dynamic(() => import("@/components/RobotScene"), { ssr: false });

export default function Page() {
  const { connection, status, sensor, history, log, lastReason, sendCommand } = useRobotSocket();
  const state = status?.state ?? "IDLE";
  const apiBase = useMemo(() => deriveApiBase(), []);

  return (
    <main className="flex h-screen w-screen flex-col bg-zinc-950 text-zinc-100">
      <header className="flex items-center justify-between border-b border-zinc-800 bg-zinc-950/80 px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="h-6 w-6 rounded-sm bg-gradient-to-br from-sky-400 to-indigo-500" />
          <h1 className="text-sm font-semibold tracking-wider">STEELMIND</h1>
          <span className="text-[10px] uppercase tracking-widest text-zinc-500">simulator</span>
        </div>
        <div className="text-[10px] font-mono text-zinc-500">
          {process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws"}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-h-0 flex-1">
          <RobotScene state={state} sensor={sensor} />
          <div className="pointer-events-none absolute left-4 top-4 rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-2 font-mono text-[11px] text-zinc-400">
            drag · zoom · {connection}
          </div>
          <EventLog entries={log} />
        </div>
        <TelemetryPanel
          connection={connection}
          status={status}
          sensor={sensor}
          history={history}
          lastReason={lastReason}
        />
      </div>

      <div className="flex justify-center border-t border-zinc-800 bg-zinc-950/80 px-4 py-3">
        <AICommandInput />
      </div>

      <CommandBar
        state={state}
        disabled={connection !== "open"}
        onCommand={sendCommand}
        apiBase={apiBase}
      />
    </main>
  );
}
