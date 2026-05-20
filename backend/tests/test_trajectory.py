"""Trajectory primitive semantics."""

import math

from backend.trajectory import compose, hold, linear, min_jerk, sinusoid


def test_hold_is_constant() -> None:
    h = hold({"a": 1.0}, duration=2.0)
    assert h.sample(0.0) == {"a": 1.0}
    assert h.sample(1.0) == {"a": 1.0}
    assert h.sample(5.0) == {"a": 1.0}  # clamped past end
    assert h.duration == 2.0


def test_linear_endpoints_exact() -> None:
    line = linear({"a": 0.0}, {"a": 10.0}, duration=2.0)
    assert line.sample(0.0)["a"] == 0.0
    assert line.sample(2.0)["a"] == 10.0
    # Midpoint == 5.0 for linear.
    assert abs(line.sample(1.0)["a"] - 5.0) < 1e-9


def test_min_jerk_smoother_than_linear() -> None:
    """Quintic min-jerk should give a slower departure from start and
    slower approach to end than linear — at t=duration/4 the value should
    be less than what linear would give."""
    duration = 2.0
    mj = min_jerk({"a": 0.0}, {"a": 10.0}, duration=duration)
    lin = linear({"a": 0.0}, {"a": 10.0}, duration=duration)
    t_early = duration / 4
    assert mj.sample(t_early)["a"] < lin.sample(t_early)["a"]


def test_sinusoid_oscillates_around_base() -> None:
    s = sinusoid(
        base={"a": 0.0},
        amplitudes={"a": 1.0},
        frequency_hz=1.0,
        duration=1.0,
    )
    # Quarter period peaks.
    assert abs(s.sample(0.25)["a"] - 1.0) < 1e-6
    assert abs(s.sample(0.75)["a"] + 1.0) < 1e-6
    # Zero crossings.
    assert abs(s.sample(0.0)["a"]) < 1e-9
    assert abs(s.sample(0.5)["a"]) < 1e-6


def test_compose_sums_durations_and_dispatches() -> None:
    seg1 = hold({"a": 1.0}, duration=1.0)
    seg2 = hold({"a": 2.0}, duration=1.5)
    seg3 = hold({"a": 3.0}, duration=0.5)
    c = compose(seg1, seg2, seg3)
    assert c.duration == 3.0
    assert c.sample(0.5)["a"] == 1.0
    assert c.sample(1.5)["a"] == 2.0
    assert c.sample(2.8)["a"] == 3.0


def test_sinusoid_phase_offsets() -> None:
    s = sinusoid(
        base={"a": 0.0, "b": 0.0},
        amplitudes={"a": 1.0, "b": 1.0},
        frequency_hz=1.0,
        duration=1.0,
        phase_offsets={"b": math.pi},
    )
    # With phase=π, b is the negative of a everywhere.
    for t in (0.1, 0.3, 0.6):
        sample = s.sample(t)
        assert abs(sample["a"] + sample["b"]) < 1e-9
