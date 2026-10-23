from .bilibili import run_all_crawlers as bilibili_crawl

def run_all_crawlers(**kwargs):
    data = bilibili_crawl(**kwargs)
    return data
