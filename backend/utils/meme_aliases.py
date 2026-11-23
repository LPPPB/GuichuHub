"""Read-only, versioned meme aliases and conservative spelling normalization."""

import json
from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata


def normalize_meme_name(word):
    """Keep word separators/punctuation; remove decorative gaps between Han chars."""
    text = unicodedata.normalize('NFKC', word)
    text = re.sub(r'\s+', ' ', text).strip()
    return re.sub(r'(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])', '', text)


def normalize_meme_key(word):
    return normalize_meme_name(word).casefold()


def normalize_meme_text_with_spans(text):
    """Return the matching key and each output character's original source span."""
    pieces, spans = [], []
    for position, char in enumerate(text):
        piece = unicodedata.normalize('NFKC', char).casefold()
        pieces.append(piece)
        spans.extend([(position, position + 1)] * len(piece))
    approximate = ''.join(pieces)
    normalized = unicodedata.normalize('NFKC', text).casefold()
    # Combining sequences and Hangul Jamo can compose across input characters.
    # Most titles take the fast equal path; reconcile only those rare changes.
    if approximate != normalized:
        corrected = []
        for operation, left, right, start, end in SequenceMatcher(
                None, approximate, normalized, autojunk=False).get_opcodes():
            if operation == 'equal':
                corrected.extend(spans[left:right])
            elif end > start:
                source = spans[left:right] or spans[max(0, left - 1):left] or [(0, 0)]
                span = (min(s[0] for s in source), max(s[1] for s in source))
                corrected.extend([span] * (end - start))
        spans = corrected
    characters, collapsed_spans = [], []
    for char, span in zip(normalized, spans):
        char = ' ' if char.isspace() else char
        if char == ' ' and characters and characters[-1] == ' ':
            collapsed_spans[-1] = (collapsed_spans[-1][0], span[1])
        else:
            characters.append(char)
            collapsed_spans.append(span)
    while characters and characters[-1] == ' ':
        characters.pop()
        collapsed_spans.pop()
    start = 0
    while start < len(characters) and characters[start] == ' ':
        start += 1
    characters, collapsed_spans = characters[start:], collapsed_spans[start:]
    keep = [i for i, char in enumerate(characters)
            if not (char == ' ' and 0 < i < len(characters) - 1 and
                    '\u3400' <= characters[i - 1] <= '\u9fff' and
                    '\u3400' <= characters[i + 1] <= '\u9fff')]
    return ''.join(characters[i] for i in keep), [collapsed_spans[i] for i in keep]


def is_meme_word_character(char):
    return char.isalnum() or unicodedata.category(char).startswith('M')


class MemeAliasIndex:
    def __init__(self, records):
        if not isinstance(records, list):
            raise ValueError('meme aliases must be a list')
        self._by_key = {}
        spellings = set()
        identifiers = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('invalid meme alias record')
            identifier = record.get('id')
            if (not isinstance(identifier, str) or
                    not re.fullmatch(r'meme_[a-z0-9_-]{1,100}', identifier) or
                    identifier in identifiers):
                raise ValueError('invalid or duplicate meme id')
            identifiers.add(identifier)
            name = record.get('name')
            aliases = record.get('aliases')
            if (not isinstance(name, str) or not normalize_meme_name(name) or
                    not isinstance(aliases, list)):
                raise ValueError('invalid meme name or aliases')
            canonical = normalize_meme_name(name)
            for spelling in [name, *aliases]:
                if not isinstance(spelling, str) or not normalize_meme_key(spelling):
                    raise ValueError('empty or invalid meme alias')
                key = normalize_meme_key(spelling)
                previous = self._by_key.get(key)
                if previous is not None and previous[0] != identifier:
                    raise ValueError(f'alias conflict for {spelling!r}')
                self._by_key[key] = (identifier, canonical)
                spellings.add(spelling.strip())
        self._spellings = tuple(sorted(spellings))

    def resolve(self, word):
        key = normalize_meme_key(word)
        return self._by_key.get(key, ('auto:' + key, normalize_meme_name(word)))

    def terms(self):
        return self._spellings


def _release_aliases():
    payload = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
    if payload.get('version') != 1:
        raise ValueError('unsupported meme alias version')
    return MemeAliasIndex(payload.get('memes'))


_RELEASE_ALIASES = _release_aliases()


def load_meme_aliases():
    """Return release configuration; never reads or writes mutable runtime state."""
    return _RELEASE_ALIASES
