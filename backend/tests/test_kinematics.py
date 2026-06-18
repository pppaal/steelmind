"""Planar FK/IK math. The IK is verified by the FK round-trip: pick angles,
compute the tip with FK, hand that point to IK, and confirm IK lands the tip
within tolerance (the joint solution itself may differ — arms are redundant)."""

import math

import pytest

from backend.kinematics import Link, PlanarChain, chain_from_config


def _two_link(l1: float = 1.0, l2: float = 1.0) -> PlanarChain:
    return PlanarChain(links=[Link("j1", l1), Link("j2", l2)])


def test_forward_straight_arm() -> None:
    chain = _two_link()
    # All zeros → fully extended along +x.
    x, y = chain.forward({"j1": 0.0, "j2": 0.0})
    assert abs(x - 2.0) < 1e-9
    assert abs(y) < 1e-9


def test_forward_right_angle() -> None:
    chain = _two_link()
    # j1 = 90° → first link points +y; j2 = 0 → second link continues +y.
    x, y = chain.forward({"j1": math.pi / 2, "j2": 0.0})
    assert abs(x) < 1e-9
    assert abs(y - 2.0) < 1e-9


def test_reach_equals_sum_of_links() -> None:
    assert _two_link(0.5, 0.3).reach == 0.8


def test_workspace_full_range_is_disc_to_full_reach() -> None:
    env = _two_link(1.0, 1.0).workspace()
    assert env["reach"] == 2.0
    assert env["outer_radius"] == pytest.approx(2.0, abs=1e-6)
    # Equal links can fold tip back onto the base → inner radius ~0.
    assert env["inner_radius"] == pytest.approx(0.0, abs=1e-3)
    assert env["outer_radius"] <= env["reach"] + 1e-9


def test_workspace_limits_shrink_the_annulus() -> None:
    # Pinning the elbow near straight stops the arm folding, so the inner
    # radius jumps up and the envelope becomes a thin ring near full reach.
    env = _two_link(1.0, 1.0).workspace(
        limits={"j1": (-math.pi, math.pi), "j2": (-0.1, 0.1)}
    )
    assert env["inner_radius"] > 1.9
    assert env["outer_radius"] == pytest.approx(2.0, abs=1e-6)


@pytest.mark.parametrize(
    "target",
    [(1.5, 0.5), (0.5, 1.2), (-0.8, 0.8), (1.0, -1.0), (0.2, 1.8)],
)
def test_ik_round_trip_reachable(target) -> None:
    chain = _two_link()
    angles, reached, residual = chain.inverse(
        target, seed={"j1": 0.3, "j2": 0.3}, limits={"j1": (-math.pi, math.pi), "j2": (-math.pi, math.pi)}
    )
    assert reached, f"did not reach {target}, residual={residual}"
    # Confirm FK of the solution actually lands on the target.
    fx, fy = chain.forward(angles)
    assert math.hypot(fx - target[0], fy - target[1]) < 1e-2


def test_ik_unreachable_returns_closest() -> None:
    chain = _two_link()  # reach = 2.0
    # (5, 0) is way outside the workspace.
    angles, reached, _ = chain.inverse((5.0, 0.0), seed={"j1": 0.1, "j2": 0.1})
    assert not reached
    fx, fy = chain.forward(angles)
    # Closest reachable point is the fully-extended tip at distance ~2.0.
    assert abs(math.hypot(fx, fy) - 2.0) < 0.05


def test_ik_respects_joint_limits() -> None:
    chain = _two_link()
    limits = {"j1": (0.0, math.radians(30)), "j2": (0.0, math.radians(30))}
    angles, _, _ = chain.inverse((1.9, 0.2), seed={"j1": 0.0, "j2": 0.0}, limits=limits)
    assert 0.0 <= angles["j1"] <= math.radians(30) + 1e-9
    assert 0.0 <= angles["j2"] <= math.radians(30) + 1e-9


def test_three_link_chain_reaches() -> None:
    chain = PlanarChain(links=[Link("a", 1.0), Link("b", 0.8), Link("c", 0.5)])
    target = (1.2, 1.0)
    angles, reached, residual = chain.inverse(target, seed={"a": 0.2, "b": 0.2, "c": 0.2})
    assert reached, residual
    fx, fy = chain.forward(angles)
    assert math.hypot(fx - target[0], fy - target[1]) < 1e-2


def test_base_offset_applied() -> None:
    chain = PlanarChain(links=[Link("j1", 1.0)], base_x=2.0, base_y=3.0)
    x, y = chain.forward({"j1": 0.0})
    assert (round(x, 6), round(y, 6)) == (3.0, 3.0)


def test_chain_from_config_parses() -> None:
    data = {
        "chain": {
            "base": [0.1, 0.0],
            "links": [{"joint": "shoulder_lift", "length": 0.12}, {"joint": "elbow_flex", "length": 0.1}],
        }
    }
    chain = chain_from_config(data)
    assert chain is not None
    assert chain.base_x == 0.1
    assert [link.joint for link in chain.links] == ["shoulder_lift", "elbow_flex"]
    assert abs(chain.reach - 0.22) < 1e-9


def test_chain_from_config_absent() -> None:
    assert chain_from_config({"joints": []}) is None
