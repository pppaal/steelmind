"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import AICommandInput from "@/components/AICommandInput";
import CameraPanel from "@/components/CameraPanel";
import CommandBar from "@/components/CommandBar";
import DeadmanButton from "@/components/DeadmanButton";
import DemoPanel from "@/components/DemoPanel";
import EventLog from "@/components/EventLog";
import RecordingPanel from "@/components/RecordingPanel";
import HardwarePanel from "@/components/HardwarePanel";
import KeyboardShortcuts from "@/components/KeyboardShortcuts";
import TelemetryPanel from "@/components/TelemetryPanel";
import { deriveApiBase } from "@/lib/api";
import { useRobotSocket } from "@/lib/useRobotSocket";

const RobotScene = dynamic(() => import("@/components/RobotScene"), { ssr: false });

export default function Page() {
  const { connection, status, sensor, history, log, lastReason, routine, sendCommand, sendDeadman } =
    useRobotSocket();
  const state = status?.state ?? "IDLE";
  const apiBase = useMemo(() => deriveApiBase(), []);

  // Joint names are discovered from the live sensor stream and cached so the
  // jog panel stays stable even between frames where a joint is momentarily
  // absent.
  const jointSeen = useRef<Set<string>>(new Set());
  const [jointNames, setJointNames] = useState<string[]>([]);
  useEffect(() => {
    if (!sensor) return;
    let changed = false;
    for (const name of Object.keys(sensor.joint_positions)) {
      if (!jointSeen.current.has(name)) {
        jointSeen.current.add(name);
        changed = true;
      }
    }
    if (changed) setJointNames([...jointSeen.current].sort());
  }, [sensor]);

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

      {connection !== "open" && (
        <div
          role="alert"
          className={`px-5 py-2 text-center text-xs font-medium ${
            connection === "connecting"
              ? "bg-amber-950/70 text-amber-300"
              : "bg-rose-950/80 text-rose-200"
          }`}
        >
          {connection === "connecting"
            ? "Connecting to robot…"
            : "Connection lost — commands will not be sent. Reconnecting…"}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="relative min-h-0 flex-1">
          <RobotScene state={state} sensor={sensor} />
          <div className="pointer-events-none absolute left-4 top-4 rounded-md border border-zinc-800 bg-zinc-950/80 px-3 py-2 font-mono text-[11px] text-zinc-400">
            drag · zoom · {connection}
          </div>
          <KeyboardShortcuts enabled={connection === "open"} onCommand={sendCommand} />
          <CameraPanel apiBase={apiBase} />
          <RecordingPanel apiBase={apiBase} />
          <DemoPanel apiBase={apiBase} />
          <EventLog entries={log} />
        </div>
        <HardwarePanel
          apiBase={apiBase}
          jointNames={jointNames}
          routine={routine}
          serverEstopped={Boolean(status?.error)}
        />
        <TelemetryPanel
          connection={connection}
          status={status}
          sensor={sensor}
          history={history}
          lastReason={lastReason}
        />
      </div>

      <div className="flex items-center justify-center gap-3 border-t border-zinc-800 bg-zinc-950/80 px-4 py-3">
        <DeadmanButton onPing={sendDeadman} enabled={connection === "open"} />
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
