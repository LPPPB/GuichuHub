"""Mandatory whole-term noise and malformed-token checks for meme candidates."""

from utils.stopwords import IGNORE_WORDS, STOPWORDS

_GENERIC_MEME_WORDS = frozenset(word.casefold() for word in {
    *STOPWORDS, *IGNORE_WORDS,
    '一首', '神曲', '魔性', '计划', '企划', '活动',
    '音乐推荐', '音乐电台', '音乐资讯', '循环歌曲', '无损音质',
    '推荐', '电台', '资讯', '无损', '音质',
})
_OPEN_TO_CLOSE = dict(zip('【「『《〈（(“[{', '】」』》〉）)”]}'))
_CLOSING = frozenset(_OPEN_TO_CLOSE.values())


def is_meme_noise(word, *, allowed_words=()):
    """Reject exact generic labels and tokens containing unbalanced delimiters."""
    if len(word) < 2 or word.isdigit():
        return True
    if not any(char.isalnum() for char in word):
        return True
    stack = []
    for char in word:
        if char in _OPEN_TO_CLOSE:
            stack.append(_OPEN_TO_CLOSE[char])
        elif char in _CLOSING:
            if not stack or stack.pop() != char:
                return True
    if stack or word.count('"') % 2 != 0:
        return True
    if word in allowed_words:
        return False
    if word.casefold() in _GENERIC_MEME_WORDS:
        return True
    return word.isascii() and word.replace(' ', '').isalnum() and len(word) <= 5
