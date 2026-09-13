"""分区常量统一收口 回归测试。

背景（2026-08-01 全面排查）：分区集合曾在 config/bilibili.py/scorer.py/db.py
多处硬编码且相互漂移：
- scorer 原硬编码 kichu_tids={119,216,217,218,221}，把喵星人(218)/野生动物(221)/
  动物圈(217)误当鬼畜最高档加分，且漏掉正牌子分区 22/26/126
- db.py 爆发榜 SQL 硬编码 tid IN (22,26,126,216,119)，未跟随 config
本次统一到 config.py 唯一真源，本测试锁定修复后的不变量。
"""
from config import (
    KICHU_TIDS, KICHU_TIDS_WITH_PARENT, MUSIC_TIDS, FUNNY_TIDS,
    MUSIC_TID, FUNNY_TID,
)
from collectors.bilibili import KICHU_TIDS as BILI_KICHU_TIDS


# ────────────── config 唯一真源 ──────────────

def test_config_is_single_source_of_truth():
    """bilibili 模块的 KICHU_TIDS 应直接引用 config，值一致"""
    assert BILI_KICHU_TIDS is KICHU_TIDS  # 同一对象（模块级 import 绑定）


def test_kichu_tids_with_parent():
    """评分/查询集合含父分区 119 兜底，但采集集合不含"""
    assert KICHU_TIDS == {22, 26, 126, 216}
    assert KICHU_TIDS_WITH_PARENT == {22, 26, 126, 216, 119}
    assert 119 not in KICHU_TIDS


def test_music_funny_tids_contain_primary():
    """音乐/搞笑主分区 ID 应在其子分区集合中"""
    assert MUSIC_TID in MUSIC_TIDS
    assert FUNNY_TID in FUNNY_TIDS
