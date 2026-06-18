from __future__ import annotations

# AI latency histogram bucket upper bounds, milliseconds.
AI_LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000, 10000)


class Metrics:
    """Tiny counter+histogram set rendered as Prometheus text on /metrics."""

    def __init__(self) -> None:
        self.transitions_total = 0
        self.ai_commands_total = 0
        self.ai_repairs_total = 0
        self.ai_errors_total = 0
        self.rate_limited_total = 0
        self.sensor_frames_total = 0
        self.overload_stops_total = 0
        self.deadman_stops_total = 0
        # AI latency histogram: cumulative counts per upper bound (ms).
        self._latency_bucket_counts = [0] * len(AI_LATENCY_BUCKETS_MS)
        self._latency_overflow = 0
        self._latency_sum_ms = 0.0
        self._latency_count = 0

    def observe_ai_latency_ms(self, ms: float) -> None:
        self._latency_sum_ms += ms
        self._latency_count += 1
        for i, upper in enumerate(AI_LATENCY_BUCKETS_MS):
            if ms <= upper:
                self._latency_bucket_counts[i] += 1
                return
        self._latency_overflow += 1

    def _histogram_lines(self) -> list[str]:
        lines = [
            "# HELP steelmind_ai_latency_ms AI commander translate() wall time.",
            "# TYPE steelmind_ai_latency_ms histogram",
        ]
        cumulative = 0
        for i, upper in enumerate(AI_LATENCY_BUCKETS_MS):
            cumulative += self._latency_bucket_counts[i]
            lines.append(f'steelmind_ai_latency_ms_bucket{{le="{upper}"}} {cumulative}')
        cumulative += self._latency_overflow
        lines.append(f'steelmind_ai_latency_ms_bucket{{le="+Inf"}} {cumulative}')
        lines.append(f"steelmind_ai_latency_ms_sum {self._latency_sum_ms:.3f}")
        lines.append(f"steelmind_ai_latency_ms_count {self._latency_count}")
        return lines

    def render(self, *, ws_clients: int, ai_history: int, ai_sessions: int) -> str:
        lines = [
            "# HELP steelmind_transitions_total Total state transitions broadcast.",
            "# TYPE steelmind_transitions_total counter",
            f"steelmind_transitions_total {self.transitions_total}",
            "# HELP steelmind_ai_commands_total AI commander requests successfully translated.",
            "# TYPE steelmind_ai_commands_total counter",
            f"steelmind_ai_commands_total {self.ai_commands_total}",
            "# HELP steelmind_ai_repairs_total AI plans repaired after validator rejection.",
            "# TYPE steelmind_ai_repairs_total counter",
            f"steelmind_ai_repairs_total {self.ai_repairs_total}",
            "# HELP steelmind_ai_errors_total AI commander upstream/translation errors.",
            "# TYPE steelmind_ai_errors_total counter",
            f"steelmind_ai_errors_total {self.ai_errors_total}",
            "# HELP steelmind_rate_limited_total AI requests rejected by the rate limiter.",
            "# TYPE steelmind_rate_limited_total counter",
            f"steelmind_rate_limited_total {self.rate_limited_total}",
            "# HELP steelmind_sensor_frames_total Sensor frames broadcast over /ws.",
            "# TYPE steelmind_sensor_frames_total counter",
            f"steelmind_sensor_frames_total {self.sensor_frames_total}",
            "# HELP steelmind_overload_stops_total Protective stops triggered by joint overload.",
            "# TYPE steelmind_overload_stops_total counter",
            f"steelmind_overload_stops_total {self.overload_stops_total}",
            "# HELP steelmind_deadman_stops_total Motion freezes triggered by deadman release.",
            "# TYPE steelmind_deadman_stops_total counter",
            f"steelmind_deadman_stops_total {self.deadman_stops_total}",
            "# HELP steelmind_ws_clients Current connected WebSocket clients.",
            "# TYPE steelmind_ws_clients gauge",
            f"steelmind_ws_clients {ws_clients}",
            "# HELP steelmind_ai_history Total AI conversation memory turns across sessions.",
            "# TYPE steelmind_ai_history gauge",
            f"steelmind_ai_history {ai_history}",
            "# HELP steelmind_ai_sessions Distinct AI conversation sessions.",
            "# TYPE steelmind_ai_sessions gauge",
            f"steelmind_ai_sessions {ai_sessions}",
            *self._histogram_lines(),
            "",
        ]
        return "\n".join(lines)
