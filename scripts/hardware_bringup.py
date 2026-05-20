#!/usr/bin/env python3
"""Interactive hardware bring-up + calibration tool.

Run this ONCE when your servos are wired and powered, BEFORE starting the
main server against real hardware. It talks to the bus directly (not
through the FastAPI app) so you can validate wiring in isolation.

    python scripts/hardware_bringup.py --config backend/configs/so100_arm.json \
        --backend lerobot --port /dev/ttyUSB0

Steps it walks you through:
  1. ping  — confirm every configured servo answers on the bus
  2. read  — print current positions (torque OFF, so you can pose by hand)
  3. zero  — set the current physical pose as logical zero, save calibration
  4. jog   — nudge one joint a few degrees to confirm direction/sign
  5. test  — run a tiny safe sweep on one joint

SAFETY: keep a hand on the power switch. Start with one lightly-loaded
joint. If a joint runs the wrong way, use 'invert' in the config and re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.calibration import Calibration
from backend.hardware import build_hardware
from backend.robot_config import load_config


def _deg(rad: float) -> str:
    return f"{math.degrees(rad):+7.2f}°"


async def cmd_ping(hw, joints) -> None:
    print("Pinging bus...")
    try:
        snap = await hw.read()
    except Exception as e:
        print(f"  read() FAILED: {e}")
        print("  → check power, port, baud, and that IDs match the config.")
        return
    for spec in joints:
        seen = spec.name in snap.joints
        mark = "ok " if seen else "MISSING"
        print(f"  [{mark}] {spec.name} (id={spec.hardware_id})")
    if snap.warnings:
        print(f"  warnings: {snap.warnings}")


async def cmd_read(hw, joints) -> None:
    await hw.disable()  # torque off — you can move joints by hand
    print("Torque OFF. Current positions (pose the robot by hand to inspect):")
    snap = await hw.read()
    for spec in joints:
        js = snap.joints.get(spec.name)
        if js:
            print(f"  {spec.name:16s} {_deg(js.position)}")


async def cmd_zero(hw, joints, calib: Calibration) -> None:
    await hw.disable()
    input("Pose the robot into its ZERO stance, then press Enter...")
    snap = await hw.read()
    offsets: dict[str, float] = {}
    for spec in joints:
        js = snap.joints.get(spec.name)
        if js is None:
            continue
        # The joint currently reads js.position with the EXISTING offset
        # folded in. To make this pose read as 0, add js.position to the
        # stored calibration offset.
        offsets[spec.name] = calib.offset_for(spec.name) + js.position
    await calib.set_many(offsets)
    print(f"Saved calibration for {len(offsets)} joints to {calib.path}")
    for name, off in offsets.items():
        print(f"  {name:16s} offset {_deg(off)}")


async def cmd_jog(hw, joints) -> None:
    names = [j.name for j in joints]
    print("Joints:", ", ".join(names))
    name = input("Jog which joint? ").strip()
    spec = next((j for j in joints if j.name == name), None)
    if spec is None:
        print("  no such joint")
        return
    try:
        deg = float(input("Delta degrees (small! e.g. 5): ").strip())
    except ValueError:
        print("  not a number")
        return
    await hw.enable()
    snap = await hw.read()
    cur = snap.joints[name].position if name in snap.joints else 0.0
    target = spec.clamp(cur + math.radians(deg))
    await hw.write({name: target})
    await asyncio.sleep(1.0)
    snap2 = await hw.read()
    new = snap2.joints[name].position if name in snap2.joints else cur
    print(f"  {name}: {_deg(cur)} → commanded {_deg(target)} → now {_deg(new)}")
    print("  If it moved the WRONG way, set \"invert\": true in the config.")


async def cmd_sweep(hw, joints) -> None:
    name = input("Sweep which joint? ").strip()
    spec = next((j for j in joints if j.name == name), None)
    if spec is None:
        print("  no such joint")
        return
    await hw.enable()
    amp = math.radians(10)
    print("  small ±10° sweep, 3 cycles. Ctrl-C to abort.")
    import time

    t0 = time.monotonic()
    while time.monotonic() - t0 < 6.0:
        t = time.monotonic() - t0
        target = spec.clamp(amp * math.sin(t * 2))
        await hw.write({name: target})
        await asyncio.sleep(0.05)
    await hw.write({name: 0.0})
    print("  done.")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--backend", default="dynamixel", choices=["dynamixel", "lerobot", "mock"])
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--calibration", default="calibration.json")
    args = ap.parse_args()

    os.environ["ROBOT_HARDWARE"] = args.backend
    os.environ["ROBOT_HARDWARE_PORT"] = args.port

    joints = load_config(args.config)
    calib = Calibration(args.calibration)
    await calib.load()
    # Fold existing calibration so reads are in the calibrated frame.
    import dataclasses

    joints = [dataclasses.replace(j, offset=j.offset + calib.offset_for(j.name)) for j in joints]

    hw = build_hardware(joints)
    await hw.init()
    print(f"Connected: {args.backend} on {args.port}, {len(joints)} joints\n")

    menu = {
        "1": ("ping bus", lambda: cmd_ping(hw, joints)),
        "2": ("read positions (torque off)", lambda: cmd_read(hw, joints)),
        "3": ("set zero + save calibration", lambda: cmd_zero(hw, joints, calib)),
        "4": ("jog one joint", lambda: cmd_jog(hw, joints)),
        "5": ("sweep test one joint", lambda: cmd_sweep(hw, joints)),
    }
    try:
        while True:
            print("\n".join(f"  {k}) {v[0]}" for k, v in menu.items()))
            print("  q) quit")
            choice = input("> ").strip().lower()
            if choice == "q":
                break
            action = menu.get(choice)
            if action:
                try:
                    await action[1]()
                except KeyboardInterrupt:
                    print("\n  aborted")
                    await hw.estop()
            else:
                print("  ?")
    finally:
        await hw.disable()
        await hw.close()
        print("Bus closed. Torque off.")


if __name__ == "__main__":
    asyncio.run(main())
