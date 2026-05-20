"""Robot config loader: degrees↔radians, optional fields, real configs."""

import json
import math
from pathlib import Path

import pytest

from backend.robot_config import load_config

CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def test_degrees_converted_to_radians(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "joints": [
            {"name": "j", "hardware_id": "1", "lower_limit_deg": -90, "upper_limit_deg": 90}
        ]
    }))
    specs = load_config(p)
    assert len(specs) == 1
    assert abs(specs[0].lower_limit + math.pi / 2) < 1e-9
    assert abs(specs[0].upper_limit - math.pi / 2) < 1e-9


def test_radians_accepted_directly(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "joints": [{"name": "j", "hardware_id": "1", "lower_limit": -1.5, "upper_limit": 1.5}]
    }))
    specs = load_config(p)
    assert specs[0].lower_limit == -1.5


def test_offset_and_invert_optional(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "joints": [{"name": "j", "hardware_id": "1", "offset_deg": 90, "invert": True}]
    }))
    specs = load_config(p)
    assert abs(specs[0].offset - math.pi / 2) < 1e-9
    assert specs[0].invert is True


def test_missing_joints_raises(tmp_path: Path) -> None:
    p = tmp_path / "cfg.json"
    p.write_text("{}")
    with pytest.raises(ValueError, match="no joints"):
        load_config(p)


@pytest.mark.parametrize(
    "config_name",
    ["sim_humanoid.json", "torso_humanoid.json", "so100_arm.json"],
)
def test_shipped_configs_load_cleanly(config_name: str) -> None:
    specs = load_config(CONFIGS_DIR / config_name)
    assert len(specs) > 0
    # Hardware IDs must be unique within a config — duplicates would cause
    # bus collisions on a real robot.
    ids = [s.hardware_id for s in specs]
    assert len(set(ids)) == len(ids), f"{config_name}: duplicate hardware_id"
    # Names must be unique too.
    names = [s.name for s in specs]
    assert len(set(names)) == len(names), f"{config_name}: duplicate joint name"
    # Limits sane.
    for s in specs:
        assert s.lower_limit < s.upper_limit, f"{config_name}: {s.name} has bad limits"
