from .bilibili import run_all_crawlers as bilibili_crawl

def run_all_crawlers():
    data = bilibili_crawl()
    return data
