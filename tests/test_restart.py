"""§6.3 restart-required notice: env drift detection + restart coordination."""

import pytest

from core import restart


@pytest.fixture()
def env_files(tmp_path, monkeypatch):
    repo_env = tmp_path / ".env"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(restart, "_REPO_ENV_PATH", repo_env)
    monkeypatch.setattr(restart, "get_data_dir", lambda: data_dir)
    return repo_env, data_dir / "config.env"


def test_no_drift_when_disk_matches_process(env_files, monkeypatch):
    repo_env, _ = env_files
    repo_env.write_text('OPENAI_API_KEY="sk-test"\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert restart.env_drift() == []


def test_drift_when_key_added_after_start(env_files, monkeypatch):
    repo_env, _ = env_files
    repo_env.write_text('OPENAI_API_KEY="sk-new"\nLLM_MODEL=gpt-5.2\n', encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert set(restart.env_drift()) == {"OPENAI_API_KEY", "LLM_MODEL"}


def test_drift_when_disk_value_changed(env_files, monkeypatch):
    repo_env, _ = env_files
    repo_env.write_text('XAI_API_KEY="xai-changed"\n', encoding="utf-8")
    monkeypatch.setenv("XAI_API_KEY", "xai-old")
    assert restart.env_drift() == ["XAI_API_KEY"]


def test_config_env_wins_over_repo_env(env_files, monkeypatch):
    # Mirrors the launcher's load order: config.env beats .env.
    repo_env, user_env = env_files
    repo_env.write_text('LLM_API_KEY="from-repo"\n', encoding="utf-8")
    user_env.write_text('LLM_API_KEY="from-config"\n', encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "from-config")
    assert restart.env_drift() == []


def test_unwatched_vars_ignored(env_files, monkeypatch):
    repo_env, _ = env_files
    repo_env.write_text("SOME_RANDOM_VAR=hello\n", encoding="utf-8")
    monkeypatch.delenv("SOME_RANDOM_VAR", raising=False)
    assert restart.env_drift() == []


def test_missing_files_mean_no_drift(env_files):
    assert restart.env_drift() == []


def test_schedule_restart_requires_hook(monkeypatch):
    monkeypatch.setattr(restart, "_SHUTDOWN_HOOK", None)
    restart._RESTART_EVENT.clear()
    assert restart.restart_supported() is False
    assert restart.schedule_restart() is False
    assert restart.restart_requested() is False


def test_schedule_restart_fires_hook(monkeypatch):
    import threading

    fired = threading.Event()
    monkeypatch.setattr(restart, "_SHUTDOWN_DELAY_SECONDS", 0.01)
    restart._RESTART_EVENT.clear()
    restart.register_shutdown_hook(fired.set)
    try:
        assert restart.restart_supported() is True
        assert restart.schedule_restart() is True
        assert restart.restart_requested() is True
        assert fired.wait(timeout=2.0)
    finally:
        restart.register_shutdown_hook(None)
        restart._RESTART_EVENT.clear()
