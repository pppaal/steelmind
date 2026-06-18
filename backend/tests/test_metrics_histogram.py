from backend.main import AI_LATENCY_BUCKETS_MS, Metrics


def test_observe_increments_correct_bucket() -> None:
    m = Metrics()
    m.observe_ai_latency_ms(75)
    m.observe_ai_latency_ms(75)
    m.observe_ai_latency_ms(600)
    m.observe_ai_latency_ms(20000)  # overflow

    out = m.render(ws_clients=0, ai_history=0, ai_sessions=0)

    # 75 ms falls into the 100 ms bucket (first >= 50), 600 into 1000.
    # Histogram lines are cumulative.
    bucket_100 = AI_LATENCY_BUCKETS_MS.index(100)  # 1
    assert 'steelmind_ai_latency_ms_bucket{le="50"} 0' in out
    assert 'steelmind_ai_latency_ms_bucket{le="100"} 2' in out
    assert 'steelmind_ai_latency_ms_bucket{le="1000"}' in out
    assert 'steelmind_ai_latency_ms_bucket{le="+Inf"} 4' in out
    assert "steelmind_ai_latency_ms_count 4" in out
    _ = bucket_100


def test_render_includes_counters_and_gauges() -> None:
    m = Metrics()
    m.transitions_total = 5
    m.ai_commands_total = 2
    out = m.render(ws_clients=3, ai_history=7, ai_sessions=2)
    assert "steelmind_transitions_total 5" in out
    assert "steelmind_ai_commands_total 2" in out
    assert "steelmind_ws_clients 3" in out
    assert "steelmind_ai_history 7" in out
    assert "steelmind_ai_sessions 2" in out


def test_render_includes_state_and_status_gauges() -> None:
    out = Metrics().render(
        ws_clients=0, ai_history=0, ai_sessions=0,
        state="WALKING", estopped=True, recording=True, replaying=False,
    )
    assert "steelmind_estopped 1" in out
    assert "steelmind_recording 1" in out
    assert "steelmind_replaying 0" in out
    # The active state reads 1, the others 0.
    assert 'steelmind_robot_state{state="WALKING"} 1' in out
    assert 'steelmind_robot_state{state="IDLE"} 0' in out
