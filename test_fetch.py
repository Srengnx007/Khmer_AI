import feedparser
import time

URLS = [
    "https://thmeythmey.com/rss",
    "https://www.khmertimeskh.com/feed/",
    "https://www.dap-news.com/feed"
]

def test_fetch():
    print("Testing RSS Fetch...")
    for url in URLS:
        print(f"Fetching {url}...")
        try:
            feed = feedparser.parse(url)
            print(f"Status: {getattr(feed, 'status', 'Unknown')}")
            print(f"Entries: {len(feed.entries)}")
            if feed.entries:
                print(f"Top Entry: {feed.entries[0].title}")
                print(f"Published: {feed.entries[0].get('published', 'N/A')}")
        except Exception as e:
            print(f"Error: {e}")
        print("-" * 20)

if __name__ == "__main__":
    test_fetch()
