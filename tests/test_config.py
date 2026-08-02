# tests/test_config.py
# Guards the three one-line config-default fixes from PRELAUNCH_CHECKLIST.md
# section H: a missed EXAM_DURATION_MS silently runs a 5-minute-short exam, a
# missed GOOGLE_MODEL_NAME silently switches models (invalidating the LLM
# cache), a missed LOG_LEVEL fills the disk with DEBUG logs during a live exam.
#
# Asserts the fallback literals in the source directly rather than the
# resolved settings.* values: local dev's .env deliberately sets LOG_LEVEL=DEBUG
# and GOOGLE_MODEL_NAME, so `settings.log_level` here would reflect .env, not
# the code-level fallback these tests exist to guard.
import pathlib

_CONFIG_SOURCE = (
    pathlib.Path(__file__).resolve().parent.parent / "app" / "utils" / "config.py"
).read_text()


def test_exam_duration_ms_fallback_is_25_minutes():
    assert 'os.getenv("EXAM_DURATION_MS", 25 * 60 * 1000)' in _CONFIG_SOURCE
    assert 'os.getenv("EXAM_DURATION_MS", 20 * 60 * 1000)' not in _CONFIG_SOURCE


def test_google_model_name_fallback_is_flash_lite():
    assert 'os.getenv("GOOGLE_MODEL_NAME", "gemini-2.5-flash-lite")' in _CONFIG_SOURCE
    assert 'os.getenv("GOOGLE_MODEL_NAME", "gemini-1.5-flash-latest")' not in _CONFIG_SOURCE


def test_log_level_fallback_is_info():
    assert 'os.getenv("LOG_LEVEL", "INFO")' in _CONFIG_SOURCE
    assert 'os.getenv("LOG_LEVEL", "DEBUG")' not in _CONFIG_SOURCE
