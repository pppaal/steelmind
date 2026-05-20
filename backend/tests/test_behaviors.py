from backend.behaviors import BEHAVIOR_DESCRIPTIONS, BEHAVIORS


def test_registry_keys_match_descriptions() -> None:
    assert set(BEHAVIORS.keys()) == set(BEHAVIOR_DESCRIPTIONS.keys())
    assert {"demo", "wave", "squat", "patrol", "dance"} <= set(BEHAVIORS.keys())


def test_each_behavior_builds_a_trajectory() -> None:
    for name, behavior in BEHAVIORS.items():
        traj = behavior.build()
        assert traj.duration > 0, f"{name}: duration must be positive"
        # Sampling at t=0 always returns a dict of joint targets.
        sample = traj.sample(0.0)
        assert isinstance(sample, dict)


def test_trajectory_clamps_t_to_duration() -> None:
    behavior = BEHAVIORS["wave"]
    traj = behavior.build()
    end_sample = traj.sample(traj.duration)
    far_future = traj.sample(traj.duration + 100.0)
    # Clamping means sampling past the end returns the final pose.
    assert end_sample == far_future


def test_advertised_duration_matches_trajectory() -> None:
    for name, behavior in BEHAVIORS.items():
        traj = behavior.build()
        # Allow tiny floating drift from compose() sums.
        assert abs(traj.duration - behavior.duration) < 0.01, (
            f"{name}: declared {behavior.duration}, built {traj.duration}"
        )
