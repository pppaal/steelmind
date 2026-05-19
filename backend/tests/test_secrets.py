import pytest

from backend.secrets import env_or_file


def test_env_takes_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    f = tmp_path / "secret.txt"
    f.write_text("from-file\n")
    monkeypatch.setenv("X", "from-env")
    monkeypatch.setenv("X_FILE", str(f))
    assert env_or_file("X") == "from-env"


def test_falls_back_to_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    f = tmp_path / "secret.txt"
    f.write_text("from-file\n")
    monkeypatch.delenv("X", raising=False)
    monkeypatch.setenv("X_FILE", str(f))
    # Trailing newline stripped for safe equality checks.
    assert env_or_file("X") == "from-file"


def test_missing_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X", raising=False)
    monkeypatch.delenv("X_FILE", raising=False)
    assert env_or_file("X", default="fallback") == "fallback"


def test_missing_file_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X", raising=False)
    monkeypatch.setenv("X_FILE", "/nonexistent/path")
    assert env_or_file("X", default="fallback") == "fallback"
