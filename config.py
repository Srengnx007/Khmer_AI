import os
import pytz
from datetime import datetime
from dotenv import load_dotenv
import logging

# Load Environment Variables
load_dotenv()

# =========================== SETTINGS ===========================

# 1. Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_LOG_CHANNEL_ID = os.getenv("TELEGRAM_LOG_CHANNEL_ID")
TELEGRAM_PERSONAL_ID = os.getenv("TELEGRAM_PERSONAL_ID", "8134594049")
TG_LINK_FOR_FB = "https://t.me/AIDailyNewsKH"

# 2. Facebook Settings
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
FB_API_VERSION = "v19.0"
FB_LINK_FOR_TG = "https://www.facebook.com/profile.php?id=61584116626111"

# 3. X (Twitter) Settings
X_API_KEY = os.getenv("X_API_KEY")
X_API_SECRET = os.getenv("X_API_SECRET")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET")
X_USERNAME = "@AIDailyNewskh"

# Social Media Links Footer
SOCIAL_MEDIA_FOOTER = """
━━━━━━━━━━━━━━━━
📢 Follow us on social media:
✈️ Telegram: https://t.me/AIDailyNewsKH  
📘 Facebook: https://www.facebook.com/profile.php?id=61584116626111  
🐦 X (Twitter): https://x.com/@AIDailyNewskh  
━━━━━━━━━━━━━━━━
"""

# 4. AI Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"

# 5. System Settings
ICT = pytz.timezone('Asia/Phnom_Penh')
DB_FILE = "posted_articles.db"
PORT = int(os.environ.get("PORT", 8080))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 6. Application Constants
CHECK_INTERVAL = 900  # 15 minutes normal cycle
SIMILARITY_THRESHOLD = 0.85
MAX_TWEET_LENGTH = 280
IMAGE_MAX_SIZE_MB = 5
POST_DELAY_BOOST = 5
POST_DELAY_NORMAL = 15
TRANSLATION_DELAY = 7
BURST_MODE_DEFAULT = False

# 7. Rate Limits (Calls per window)
RATE_LIMITS = {
    "telegram": {"calls": 20, "period": 60},     # 20/min (Safe)
    "facebook": {"calls": 10, "period": 3600},   # 10/hr (Very Safe)
    "x":        {"calls": 5, "period": 1200},    # 5/20min (Extremely Safe for Penalty Box)
    "gemini":   {"calls": 10, "period": 60},     # 10/min (Safety Buffer)
    "rss":      {"calls": 100, "period": 60}     # Internal fetch limit
}

# =========================== NEWS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        # {"name": "Thmey Thmey",    "rss": "https://thmeythmey.com/rss",                   "url": "https://thmeythmey.com"}, # 404
        {"name": "Koh Santepheap", "rss": "https://kohsantepheapdaily.com.kh/feed",        "url": "https://kohsantepheapdaily.com.kh"},
        # {"name": "DAP News",       "rss": "https://www.dap-news.com/feed",                 "url": "https://www.dap-news.com"}, # 301
        {"name": "Khmer Times",    "rss": "https://www.khmertimeskh.com/feed/",            "url": "https://www.khmertimeskh.com"},
        {"name": "Rasmei News",    "rss": "https://www.rasmeinews.com/feed",               "url": "https://www.rasmeinews.com"},
        {"name": "CamboJA News",   "rss": "https://cambojanews.com/feed/",                 "url": "https://cambojanews.com"},
        # {"name": "Post Khmer",     "rss": "https://postkhmer.com/feed",                    "url": "https://postkhmer.com"}, # 301
        # {"name": "Sabay News",     "rss": "https://news.sabay.com.kh/topics/cambodia.rss", "url": "https://news.sabay.com.kh"}, # 404
        {"name": "Kiripost",       "rss": "https://kiripost.com/feed",                     "url": "https://kiripost.com"},
        # {"name": "Cambodianess",   "rss": "https://cambodianess.com/rss.xml",              "url": "https://cambodianess.com"}, # 404
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
        # {"name": "Bangkok Post",   "rss": "https://www.bangkokpost.com/rss/feed/news",       "url": "https://www.bangkokpost.com"}, # 429
        # {"name": "Khaosod English","rss": "https://www.khaosodenglish.com/feed",             "url": "https://www.khaosodenglish.com"}, # 403
    ],
    "vietnamese": [
        {"name": "VN Express",     "rss": "https://e.vnexpress.net/rss/news.rss",            "url": "https://e.vnexpress.net"},
        {"name": "Tuoi Tre",       "rss": "https://tuoitrenews.vn/rss",                      "url": "https://tuoitrenews.vn"},
        # {"name": "VietnamNet",     "rss": "https://vietnamnet.vn/rss/english.rss",           "url": "https://vietnamnet.vn/en"}, # 404
    ],
    "china": [
        # {"name": "CGTN",           "rss": "https://www.cgtn.com/rss.xml",                    "url": "https://www.cgtn.com"}, # 404
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

# Flattened list for easy iteration
RSS_FEEDS = []
for category, feeds in NEWS_SOURCES.items():
    for feed in feeds:
        feed['category'] = category
        RSS_FEEDS.append(feed)

# =========================== HELPER FUNCTIONS ===========================

def is_breaking_news(article):
    """Detect breaking news based on keywords and source"""
    score = 0
    title = article.get('title', '').lower()
    
    # Keywords (Khmer & English)
    kws = [
        "breaking", "urgent", "shooting", "explosion", "crash", "dead", "crisis", "war", "assassination",
        "បន្ទាន់", "ភ្លាម", "បាញ់", "ផ្ទុះ", "ស្លាប់", "គ្រោះថ្នាក់", "រញ្ជួយដី", "សង្គ្រាម", "វិបត្តិ"
    ]
    
    for w in kws:
        if w in title: score += 100
        
    if "!" in title: score += 10
    
    # Boost reliable sources
    if article.get('source') in ["Khmer Times", "BBC News", "CNN", "Thmey Thmey", "Fresh News"]: 
        score += 20
    
    return score >= 100

# News Slots (Hours 0-23)
NEWS_SLOTS = [
    {"start": 7, "end": 9, "delay": 300, "max": 10, "name": "Morning Rush"},
    {"start": 11, "end": 13, "delay": 300, "max": 10, "name": "Lunch Break"},
    {"start": 17, "end": 20, "delay": 300, "max": 10, "name": "Evening News"},
    {"start": 0, "end": 24, "delay": 900, "max": 5, "name": "Standard Flow"} # Default
]

def validate_config():
    """Validate critical configuration"""
    errors = []
    required = [
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID",
        "GEMINI_API_KEY"
    ]
    missing = [key for key in required if not globals().get(key)]
    
    if missing:
        raise ValueError(f"❌ Missing Critical Env Vars: {', '.join(missing)}")
    
    # Facebook validation
    if FB_PAGE_ID and FB_ACCESS_TOKEN:
        if not FB_PAGE_ID.isdigit():
            errors.append("FB_PAGE_ID must be numeric (e.g., '123456789012345')")
        if len(FB_ACCESS_TOKEN) < 50:
            errors.append("FB_ACCESS_TOKEN appears invalid (too short, should be 100+ chars)")
    elif FB_PAGE_ID or FB_ACCESS_TOKEN:
        # One is set but not the other
        logging.warning("⚠️ Facebook partially configured. Both FB_PAGE_ID and FB_ACCESS_TOKEN are required.")
    else:
        # Neither is set
        logging.warning("⚠️ Facebook credentials missing. FB posting will be disabled.")
    
    # X (Twitter) validation
    if X_API_KEY and X_API_SECRET and X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET:
        if len(X_API_KEY) < 20:
            errors.append("X_API_KEY appears invalid (too short)")
        if len(X_API_SECRET) < 40:
            errors.append("X_API_SECRET appears invalid (too short)")
        if len(X_ACCESS_TOKEN) < 40:
            errors.append("X_ACCESS_TOKEN appears invalid (too short)")
        if len(X_ACCESS_TOKEN_SECRET) < 40:
            errors.append("X_ACCESS_TOKEN_SECRET appears invalid (too short)")
    elif any([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        # Some are set but not all
        logging.warning("⚠️ X (Twitter) partially configured. All 4 credentials are required.")
    else:
        # None are set
        logging.warning("⚠️ X (Twitter) credentials missing. X posting will be disabled.")
    
    # Raise errors if any validation failed
    if errors:
        raise ValueError(f"❌ Configuration Errors:\n  - " + "\n  - ".join(errors))
        
    return True

