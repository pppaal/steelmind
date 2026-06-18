"""Robot configuration loader. Parses a JSON or YAML file describing the
joint layout, hardware mapping, and limits, and returns JointSpec instances
the HAL can consume.

YAML support is optional — if PyYAML isn't installed, only JSON files load."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .hardware.base import JointSpec
from .kinematics import PlanarChain, chain_from_config


def _maybe_yaml_load(text: str) -> dict:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(
            "YAML config requires PyYAML — install it or use a .json config"
        ) from e
    return yaml.safe_load(text)


def _read_config(path: str | Path) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        return _maybe_yaml_load(text)
    return json.loads(text)


def load_chain(path: str | Path) -> PlanarChain | None:
    """Return the optional planar kinematic chain from a config, or None."""
    return chain_from_config(_read_config(path))


def load_config(path: str | Path) -> list[JointSpec]:
    """Load a robot config file. The file may be .json, .yaml, or .yml.

    Schema:
      joints:
        - name: shoulder_left
          hardware_id: "1"        # str — driver-specific
          lower_limit_deg: -180   # OR lower_limit (radians)
          upper_limit_deg: 180
          max_velocity: 3.0       # rad/s
          max_effort: 0.0         # optional; >0 enables overload protection
          offset_deg: 0           # optional calibration
          invert: false           # optional
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        data = _maybe_yaml_load(text)
    elif p.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        # Fall back to JSON parsing — most configs are valid either way.
        data = json.loads(text)

    raw_joints = data.get("joints", [])
    if not raw_joints:
        raise ValueError(f"config {p} has no joints")

    specs: list[JointSpec] = []
    for j in raw_joints:
        # Accept either radians (lower_limit) or degrees (lower_limit_deg).
        lower = j.get("lower_limit")
        if lower is None:
            lower = math.radians(j.get("lower_limit_deg", -180))
        upper = j.get("upper_limit")
        if upper is None:
            upper = math.radians(j.get("upper_limit_deg", 180))
        offset = j.get("offset")
        if offset is None:
            offset = math.radians(j.get("offset_deg", 0))
        specs.append(
            JointSpec(
                name=j["name"],
                hardware_id=str(j["hardware_id"]),
                lower_limit=float(lower),
                upper_limit=float(upper),
                max_velocity=float(j.get("max_velocity", 3.0)),
                max_effort=float(j.get("max_effort", 0.0)),
                offset=float(offset),
                invert=bool(j.get("invert", False)),
            )
        )
    return specs
