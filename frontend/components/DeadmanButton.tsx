"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  // Sends one hold-to-enable ping to the server.
  onPing: () => void;
  // Whether the socket is connected; the control is inert otherwise.
  enabled: boolean;
  // How often to re-ping while held (ms). Must be under the server's
  // DEADMAN_TIMEOUT_SEC so the hold never lapses mid-press.
  intervalMs?: number;
}

/**
 * Hold-to-enable ("deadman") control. While pressed it streams deadman pings;
 * releasing the button — or the pointer leaving, the window blurring, or the
 * component unmounting — stops the pings, so the server disarms motion. This
 * is a safety affordance, so it errs toward releasing.
 */
export default function DeadmanButton({ onPing, enabled, intervalMs = 300 }: Props) {
  const [held, setHeld] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const release = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setHeld(false);
  }, []);

  const press = useCallback(() => {
    if (!enabled || timerRef.current) return;
    setHeld(true);
    onPing(); // arm immediately
    timerRef.current = setInterval(onPing, intervalMs);
  }, [enabled, onPing, intervalMs]);

  // Release on unmount and whenever the window loses focus — never leave the
  // robot armed because a tab switched or the component went away.
  useEffect(() => {
    const onBlur = () => release();
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("blur", onBlur);
      release();
    };
  }, [release]);

  // If the connection drops while held, stop pretending we're armed.
  useEffect(() => {
    if (!enabled) release();
  }, [enabled, release]);

  return (
    <button
      type="button"
      aria-pressed={held}
      disabled={!enabled}
      onPointerDown={press}
      onPointerUp={release}
      onPointerLeave={release}
      onPointerCancel={release}
      className={`select-none rounded-md px-4 py-2 text-xs font-bold uppercase tracking-wider transition-colors disabled:opacity-40 ${
        held
          ? "bg-emerald-500 text-emerald-950"
          : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
      }`}
      title="Hold to enable motion (deadman switch)"
    >
      {held ? "● Armed — holding" : "Hold to enable"}
    </button>
  );
}
