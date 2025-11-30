import os
import pytz
from datetime import datetime
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

# =========================== SETTINGS ===========================

# 1. Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TG_LINK_FOR_FB = "https://t.me/AIDailyNewsKH"
TELEGRAM_PERSONAL_ID = 8134594049
TELEGRAM_LOG_CHANNEL_ID = os.getenv("TELEGRAM_LOG_CHANNEL_ID")

# 2. Facebook Settings
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
FB_LINK_FOR_TG = "https://www.facebook.com/profile.php?id=61584116626111"

# 3. AI Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"
FB_API_VERSION = "v19.0" 
CHECK_INTERVAL = 900  # 15 minutes normal cycle

# Rate Limits (Calls per window)
RATE_LIMITS = {
    "telegram": {"calls": 30, "period": 60},    # 30/min
    "facebook": {"calls": 200, "period": 3600}, # 200/hr
    "x":        {"calls": 50, "period": 900},   # 50/15min
    "gemini":   {"calls": 15, "period": 60}     # 15/min
}

# FIX #22: Application Constants
SIMILARITY_THRESHOLD = 0.85  # Duplicate detection threshold
MAX_TWEET_LENGTH = 280       # X/Twitter character limit
IMAGE_MAX_SIZE_MB = 5        # Maximum image size in MB
POST_DELAY_BOOST = 5         # Seconds between posts in boost mode
POST_DELAY_NORMAL = 15       # Seconds between posts normally
TRANSLATION_DELAY = 7        # Seconds delay for translation

# 7. X (Twitter) Settings
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
X_USERNAME = "@AIDailyNewskh"

# 4. System Settings
ICT = pytz.timezone('Asia/Phnom_Penh')
DB_FILE = "posted_articles.db"
PORT = int(os.environ.get("PORT", 8080))

# =========================== NEWS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/feed",                   "url": "https://thmeythmey.com"},
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        {"name": "DAP News",       "rss": "https://www.dap-news.com/feed",                 "url": "https://www.dap-news.com"},
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
        {"name": "Rasmei News",    "rss": "https://www.rasmeinews.com/feed",               "url": "https://www.rasmeinews.com"},
        {"name": "CamboJA News",   "rss": "https://cambojanews.com/feed/",                 "url": "https://cambojanews.com"},
        {"name": "Post Khmer",     "rss": "https://postkhmer.com/feed",                    "url": "https://postkhmer.com"},
        {"name": "Sabay News",     "rss": "https://news.sabay.com.kh/topics/cambodia.rss", "url": "https://news.sabay.com.kh"},
        {"name": "Kiripost",       "rss": "https://kiripost.com/feed",                     "url": "https://kiripost.com"},
        {"name": "Cambodianess",   "rss": "https://cambodianess.com/rss.xml",              "url": "https://cambodianess.com"},
        {"name": "AMS Central",    "rss": "https://ams.com.kh/central/feed/",              "url": "https://ams.com.kh/central"},
    ],
    "international": [
        {"name": "BBC News",       "rss": "http://feeds.bbci.co.uk/news/world/rss.xml",      "url": "https://www.bbc.com"},
        {"name": "CNN",            "rss": "http://rss.cnn.com/rss/edition.rss",              "url": "https://edition.cnn.com"},
        {"name": "Al Jazeera",     "rss": "https://www.aljazeera.com/xml/rss/all.xml",       "url": "https://www.aljazeera.com"},
        {"name": "The Guardian",   "rss": "https://www.theguardian.com/world/rss",           "url": "https://www.theguardian.com"},
        {"name": "DW News",        "rss": "https://rss.dw.com/xml/rss-en-all",               "url": "https://www.dw.com"},
        {"name": "France 24",      "rss": "https://www.france24.com/en/rss",                 "url": "https://www.france24.com"},
        {"name": "CNA",            "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml", "url": "https://www.channelnewsasia.com"},
    ],
    "thai": [
        {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed/news",       "url": "https://www.bangkokpost.com"},
        {"name": "Khaosod English","rss": "https://www.khaosodenglish.com/feed",             "url": "https://www.khaosodenglish.com"},
    ],
    "vietnamese": [
        {"name": "VN Express",     "rss": "https://e.vnexpress.net/rss/news.rss",            "url": "https://e.vnexpress.net"},
        {"name": "Tuoi Tre",       "rss": "https://tuoitrenews.vn/rss",                      "url": "https://tuoitrenews.vn"},
        {"name": "VietnamNet",     "rss": "https://vietnamnet.vn/rss/english.rss",           "url": "https://vietnamnet.vn/en"},
    ],
    "china": [
        {"name": "CGTN",           "rss": "https://www.cgtn.com/rss.xml",                    "url": "https://www.cgtn.com"},
        {"name": "China Daily",    "rss": "https://www.chinadaily.com.cn/rss/world_rss.xml", "url": "https://www.chinadaily.com.cn"},
        {"name": "SCMP",           "rss": "https://www.scmp.com/rss/91/feed",                "url": "https://www.scmp.com"},
    ],
    "tech": [
        {"name": "TechCrunch",     "rss": "https://techcrunch.com/feed/",                    "url": "https://techcrunch.com"},
        {"name": "The Verge",      "rss": "https://www.theverge.com/rss/index.xml",          "url": "https://www.theverge.com"},
    ],
    "crypto": [
        {"name": "CoinDesk",       "rss": "https://www.coindesk.com/arc/outboundfeeds/rss/", "url": "https://www.coindesk.com"},
        {"name": "CoinTelegraph",  "rss": "https://cointelegraph.com/rss",                   "url": "https://cointelegraph.com"},
    ]
}

# =========================== HELPER FUNCTIONS ===========================
def get_current_slot():
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    if 5 <= h < 8:       return {"name": "Morning 🌅",      "max": 8, "delay": 60}
    if 8 <= h < 11.5:    return {"name": "Work AM 💼",      "max": 5, "delay": 90}
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak 🍱",   "max": 8, "delay": 45}
    if 13.5 <= h < 17:   return {"name": "Afternoon ☕",    "max": 5, "delay": 120}
    if 17 <= h < 21:     return {"name": "Prime Time 📺",   "max": 10, "delay": 40}
    if 21 <= h < 23:     return {"name": "Night 🌙",        "max": 4, "delay": 150}
    return                       {"name": "Deep Night 💤",   "max": 1, "delay": 300}

def is_breaking_news(article):
    score = 0
    title = article['title'].lower()
    kws = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "crisis", "war", 
           "បន្ទាន់", "ភ្លាម", "បាញ់", "ផ្ទុះ", "ស្លាប់", "គ្រោះថ្នាក់", "រញ្ជួយដី"]
    for w in kws:
        if w in title: score += 100
    if "!" in title: score += 10
    
    if article['source'] in ["Khmer Times", "BBC News", "CNN", "Thmey Thmey"]: score += 20
    
    if article['source'] in ["Khmer Times", "BBC News", "CNN", "Thmey Thmey"]: score += 20
    
    return score >= 100

def validate_config():
    required = [
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID",
        "FB_PAGE_ID", "FB_ACCESS_TOKEN",
        "GEMINI_API_KEY",
        "X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError(f"❌ Missing Required Config: {', '.join(missing)}")
    return True
