"""Expiry is enforced by reads too; daily retention is statistics-only by default."""
import time
from services.meme_publication import get_meme_review_service


def refresh_meme_publication():
    return get_meme_review_service().read_current(int(time.time()))


def preview_meme_cleanup():
    from logger import get_logger
    result = get_meme_review_service().cleanup_batch(int(time.time()))
    get_logger(__name__).info('Meme review cleanup dry run: %s', result)
    return result
