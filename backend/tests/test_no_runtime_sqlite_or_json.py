"""Production entrypoints must not touch SQLite or JSON state files."""

import os
from pathlib import Path
import subprocess
import sys


def test_production_api_liveness_never_opens_sqlite_or_state_json(tmp_path):
    url_file = tmp_path / "api-url"
    url_file.write_text("postgresql+psycopg://api:secret@db/kichu\n", encoding="utf-8")
    state_path = tmp_path / "inspiration_db.json"
    script = """
import sqlite3
sqlite3.connect = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SQLite runtime access"))
import api_entrypoint
assert api_entrypoint.app.test_client().get('/api/health/live').status_code == 200
"""
    env = os.environ | {
        "KICHU_API_DATABASE_URL_FILE": str(url_file),
        "KICHU_STATE_PATH": str(state_path),
        "KICHU_WRITE_TOKEN": "test-token",
    }
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not state_path.exists()


def test_editable_word_rules_round_trip_in_postgres_without_opening_files(monkeypatch, postgres_runtime):
    from analytics import filters
    from collectors import bilibili

    def fail_file_access(*args, **kwargs):
        raise AssertionError("runtime JSON file access")

    monkeypatch.setattr("builtins.open", fail_file_access)

    danmaku = {"allowed_exact": ["666"], "bad_exact": ["广告"], "bad_substr": ["推广"]}
    meme = {"测试分类": ["词A", "词B"]}
    seeds = ["哈基米", "叮咚鸡"]
    tags = {
        "categories": {"测试分类": ["泛词"]},
        "ad_keywords": ["品牌"],
        "activity_keywords": ["企划"],
        "allowed_two_char": ["叮咚"],
    }

    filters.save_danmaku_filters(danmaku)
    bilibili.save_meme_stopwords(meme)
    bilibili.save_meme_seed_words(seeds)
    bilibili.save_tag_filters(tags)

    assert filters.load_danmaku_filters() == danmaku
    assert bilibili.load_meme_stopwords() == meme
    assert bilibili.load_meme_seed_words() == seeds
    assert bilibili.load_tag_filters() == tags
