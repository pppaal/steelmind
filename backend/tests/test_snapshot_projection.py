"""snapshot_to_sensor must project a HAL snapshot into the SensorData wire
format without choking on the IMU tuple → Vector3 conversion (regression:
Vector3 is a Pydantic model and rejects positional args)."""

import asyncio

from backend.hardware.base import JointSpec
from backend.hardware.mock import MockHardware
from backend.main import snapshot_to_sensor


def test_projects_mock_snapshot() -> None:
    async def _run():
        hw = MockHardware([
            JointSpec(name="shoulder_right", hardware_id="1", lower_limit=-2, upper_limit=2),
        ])
        await hw.init()
        await hw.enable()
        await hw.write({"shoulder_right": 0.5})
        return await hw.read()

    snapshot = asyncio.run(_run())
    data = snapshot_to_sensor(snapshot)
    # IMU vectors built without raising.
    assert hasattr(data.imu_orientation, "x")
    assert hasattr(data.imu_linear_acceleration, "z")
    # Joint projected through.
    assert "shoulder_right" in data.joint_positions
    # Serializes to JSON (the broadcast path).
    assert "shoulder_right" in data.model_dump_json()
