"""The shipped Grafana dashboard / Prometheus config are valid and reference
metric names the backend actually emits."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]


def test_grafana_dashboard_is_valid_json_with_panels() -> None:
    data = json.loads((_ROOT / "monitoring/grafana/dashboards/steelmind.json").read_text())
    assert data["uid"] == "steelmind"
    assert len(data["panels"]) >= 5
    # Every panel targets a steelmind_ metric.
    exprs = [t["expr"] for p in data["panels"] for t in p.get("targets", [])]
    assert exprs and all("steelmind_" in e for e in exprs)


def test_prometheus_config_targets_backend_metrics() -> None:
    text = (_ROOT / "monitoring/prometheus.yml").read_text()
    assert "/metrics" in text
    assert "backend:8000" in text


def test_metrics_endpoint_exposes_new_gauges(fresh_app: TestClient) -> None:
    body = fresh_app.get("/metrics").text
    for name in ("steelmind_estopped", "steelmind_recording", "steelmind_replaying", "steelmind_robot_state"):
        assert name in body
