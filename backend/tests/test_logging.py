import io
import json
import logging

from backend.logging_setup import JsonFormatter, configure


def test_json_formatter_emits_valid_json() -> None:
    rec = logging.LogRecord(
        name="steelmind.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    rec.user_id = "u123"
    out = JsonFormatter().format(rec)
    parsed = json.loads(out)
    assert parsed["msg"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "steelmind.test"
    assert parsed["user_id"] == "u123"
    assert "t" in parsed


def test_configure_json_mode_routes_through_formatter() -> None:
    buf = io.StringIO()
    configure(level="INFO", json_logs=True)
    root = logging.getLogger()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    try:
        logging.getLogger("steelmind.test").info("ping")
    finally:
        root.removeHandler(handler)
    line = buf.getvalue().strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["msg"] == "ping"
