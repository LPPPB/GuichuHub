"""Apply current operator exclusions without destroying collected snapshots."""


def filter_meme_sections(data: dict) -> dict:
    from collectors.bilibili import load_meme_stopwords
    from utils.meme_aliases import load_meme_aliases

    from services.meme_publication import public_review_data
    data = public_review_data(data)
    if data.get('meme_publication'):
        # The current publication already applies exclusions with its own dictionary.
        return dict(data)
    aliases = load_meme_aliases()
    blocked = {aliases.resolve(word)[0]
               for words in load_meme_stopwords().values() for word in words}
    result = dict(data)
    for field, label in (('hot_memes', 'keyword'), ('meme_materials', 'name')):
        if isinstance(data.get(field), list):
            result[field] = [row for row in data[field]
                             if not isinstance(row, dict)
                             or aliases.resolve(str(row.get(label) or ''))[0] not in blocked]
    return result
