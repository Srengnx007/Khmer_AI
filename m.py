# facebook_news_bot.py - AI News Bot for Facebook Page
# Complete production-ready code for public deployment
# Author: [Your Name]
# License: MIT
# Repository: https://github.com/yourusername/facebook-news-bot

import os
import asyncio
import json
import hashlib
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from urllib.parse import urljoin

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
import aiosqlite
from aiohttp import web

# =========================== CONFIGURATION ===========================
load_dotenv()

# Facebook Credentials
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
FB_PAGE_NAME = os.getenv("FB_PAGE_NAME", "Cambodia Daily News")
FB_API_VERSION = "v21.0"

# Gemini AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# Bot Settings
CHECK_INTERVAL = 1800  # 30 minutes
GEMINI_DELAY = 6  # Rate limiting
MAX_RETRIES = 3
IMAGE_TIMEOUT = 20

# Timezone
ICT = pytz.timezone('Asia/Phnom_Penh')

# Database
DB_FILE = "facebook_posts.db"
db_lock = asyncio.Lock()

# Web Server
PORT = int(os.environ.get("PORT", 8080))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    GEMINI_MODEL_INSTANCE = genai.GenerativeModel(GEMINI_MODEL)
else:
    GEMINI_MODEL_INSTANCE = None
    logger.warning("⚠️ GEMINI_API_KEY not set - translations will be in English")

# Statistics
stats = {
    'total_posts': 0,
    'successful_posts': 0,
    'failed_posts': 0,
    'translations': 0,
    'errors': 0,
    'start_time': datetime.now(ICT).isoformat()
}

# =========================== NEWS SOURCES ===========================
NEWS_SOURCES = {
    "cambodia": [
        {"name": "Khmer Times", "rss": "https://www.khmertimeskh.com/feed/", "url": "https://www.khmertimeskh.com"},
        {"name": "Phnom Penh Post", "rss": "https://www.phnompenhpost.com/rss", "url": "https://www.phnompenhpost.com"},
        {"name": "Fresh News", "rss": "https://www.freshnewsasia.com/index.php/en/feed", "url": "https://www.freshnewsasia.com"},
        {"name": "Cambodia Daily", "rss": "https://english.cambodiadaily.com/feed/", "url": "https://english.cambodiadaily.com"},
    ],
    "international": [
        {"name": "BBC News", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml", "url": "https://www.bbc.com"},
        {"name": "Al Jazeera", "rss": "https://www.aljazeera.com/xml/rss/all.xml", "url": "https://www.aljazeera.com"},
        {"name": "Reuters", "rss": "https://www.reuters.com/tools/rss", "url": "https://www.reuters.com"},
    ]
}

BREAKING_KEYWORDS = ["breaking", "urgent", "បន្ទាន់", "ភ្លាម"]

# =========================== DATABASE FUNCTIONS ===========================
async def init_db():
    """Initialize SQLite database"""
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE, timeout=15) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS posts (
                        article_id TEXT PRIMARY KEY,
                        category TEXT,
                        source TEXT,
                        fb_post_id TEXT,
                        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.commit()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")

async def is_posted(article_id: str) -> bool:
    """Check if article already posted"""
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE, timeout=10) as db:
                cur = await db.execute(
                    "SELECT 1 FROM posts WHERE article_id=?",
                    (article_id,)
                )
                return await cur.fetchone() is not None
    except:
        return False

async def mark_as_posted(article_id: str, category: str, source: str, fb_post_id: str = None):
    """Mark article as posted"""
    try:
        async with db_lock:
            async with aiosqlite.connect(DB_FILE, timeout=10) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO posts(article_id, category, source, fb_post_id) VALUES(?, ?, ?, ?)",
                    (article_id, category, source, fb_post_id)
                )
                await db.commit()
    except Exception as e:
        logger.error(f"❌ DB write error: {e}")

# =========================== RSS FUNCTIONS ===========================
async def fetch_rss(url: str) -> Optional[feedparser.FeedParserDict]:
    """Fetch RSS feed with retry logic"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FacebookNewsBot/1.0)"}
    
    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.text()
                        return feedparser.parse(content)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                logger.warning(f"⚠️ RSS fetch failed after {MAX_RETRIES} attempts: {url}")
            await asyncio.sleep(2)
    return None

def extract_image(entry, base_url: str) -> Optional[str]:
    """Extract image URL from RSS entry"""
    try:
        # Try media content
        if hasattr(entry, "media_content") and entry.media_content:
            for media in entry.media_content:
                if media.get("url"):
                    return media["url"]
        
        # Try media thumbnail
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            for media in entry.media_thumbnail:
                if media.get("url"):
                    return media["url"]
        
        # Try enclosures
        if hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                if hasattr(enc, 'type') and enc.type and "image" in enc.type and enc.url:
                    return enc.url
        
        # Parse HTML content
        content = entry.get("summary", "") or entry.get("description", "")
        if content:
            soup = BeautifulSoup(content, "html.parser")
            img = soup.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if src:
                    return urljoin(base_url, src)
    except Exception as e:
        logger.debug(f"Image extraction error: {e}")
    return None

def generate_article_id(title: str, link: str) -> str:
    """Generate unique article ID"""
    return hashlib.md5(f"{title}{link}".encode()).hexdigest()

# =========================== GEMINI AI TRANSLATION ===========================
async def translate_with_gemini(article: Dict[str, str]) -> Dict[str, str]:
    """Translate article to Khmer using Gemini AI"""
    
    if not GEMINI_MODEL_INSTANCE:
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        article["hashtags"] = ["#Cambodia", "#News", "#ព័ត៌មាន"]
        return article
    
    prompt = f"""You are a professional Khmer news editor for Facebook.

Article to translate:
Title: {article['title']}
Content: {article['summary'][:2000]}
Source: {article['source']}

Create engaging Facebook post in Khmer:
1. Catchy title (ចំណងជើងទាក់ទាញ)
2. Clear summary (3-4 sentences explaining key points)
3. 5 relevant hashtags (mix Khmer & English)

Return ONLY valid JSON:
{{
    "title_kh": "ចំណងជើងខ្មែរ",
    "body_kh": "សង្ខេប 3-4 ប្រយោគជាភាសាខ្មែរ",
    "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]
}}"""
    
    try:
        response = await asyncio.to_thread(
            GEMINI_MODEL_INSTANCE.generate_content,
            prompt
        )
        
        # Clean response
        text = re.sub(r"^```json\s*|```$", "", response.text.strip(), flags=re.M)
        data = json.loads(text)
        
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        article["hashtags"] = data.get("hashtags", ["#Cambodia", "#News", "#ព័ត៌មាន"])
        
        stats['translations'] += 1
        await asyncio.sleep(GEMINI_DELAY)
        
        logger.info(f"✅ Translated: {article['title'][:40]}...")
        return article
        
    except Exception as e:
        logger.error(f"❌ Translation failed: {e}")
        stats['errors'] += 1
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        article["hashtags"] = ["#Cambodia", "#News"]
        return article

# =========================== FACEBOOK POSTING ===========================
def format_facebook_post(article: Dict[str, str]) -> str:
    """Format article for Facebook post"""
    
    emoji = "🇰🇭" if article.get("category") == "cambodia" else "🌍"
    
    # Check for breaking news
    title_lower = article["title"].lower()
    is_breaking = any(keyword in title_lower for keyword in BREAKING_KEYWORDS)
    if is_breaking:
        emoji = "🚨 " + emoji
    
    message = f"""{emoji} {article['title_kh']}

{article['body_kh']}

━━━━━━━━━━━━━━━━━
📌 ប្រភព: {article['source']}
🕐 {datetime.now(ICT).strftime('%d/%m/%Y • %H:%M')}

{' '.join(article.get('hashtags', []))}

#{FB_PAGE_NAME.replace(' ', '')}"""
    
    return message.strip()

async def post_to_facebook(article: Dict[str, str], message: str) -> Optional[str]:
    """Post article to Facebook Page"""
    
    if not (FB_PAGE_ID and FB_ACCESS_TOKEN):
        logger.error("❌ Facebook credentials missing")
        return None
    
    # Try photo post first
    if article.get("image_url"):
        try:
            url = f"https://graph.facebook.com/{FB_API_VERSION}/{FB_PAGE_ID}/photos"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data={
                    "url": article["image_url"],
                    "message": message,
                    "access_token": FB_ACCESS_TOKEN
                }) as response:
                    result = await response.json()
                    
                    if result.get("id"):
                        post_id = result["id"]
                        logger.info(f"📸 FB photo posted: {post_id}")
                        stats['successful_posts'] += 1
                        return post_id
                    else:
                        logger.warning(f"⚠️ Photo post failed: {result}")
        except Exception as e:
            logger.warning(f"⚠️ Photo upload failed: {e}")
    
    # Fallback to link post
    try:
        url = f"https://graph.facebook.com/{FB_API_VERSION}/{FB_PAGE_ID}/feed"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={
                "link": article["link"],
                "message": message,
                "access_token": FB_ACCESS_TOKEN
            }) as response:
                result = await response.json()
                
                if result.get("id"):
                    post_id = result["id"]
                    logger.info(f"📝 FB link posted: {post_id}")
                    stats['successful_posts'] += 1
                    return post_id
                else:
                    logger.error(f"❌ Link post failed: {result}")
                    stats['failed_posts'] += 1
                    
    except Exception as e:
        logger.error(f"❌ Facebook API error: {e}")
        stats['errors'] += 1
        stats['failed_posts'] += 1
    
    return None

# =========================== POSTING SCHEDULE ===========================
def get_posting_schedule() -> Dict:
    """Get current posting schedule based on time"""
    now = datetime.now(ICT)
    hour = now.hour
    
    # Prime time: more posts
    if 6 <= hour < 9:
        return {"max_posts": 3, "name": "Morning"}
    elif 11 <= hour < 13:
        return {"max_posts": 4, "name": "Lunch"}
    elif 17 <= hour < 21:
        return {"max_posts": 5, "name": "Evening Prime"}
    else:
        return {"max_posts": 2, "name": "Off-peak"}

# =========================== MAIN WORKER ===========================
async def worker():
    """Main worker loop"""
    
    await init_db()
    
    logger.info("=" * 60)
    logger.info("🚀 Facebook News Bot Started!")
    logger.info(f"📘 Page: {FB_PAGE_NAME}")
    logger.info(f"⏰ Check interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL//60} minutes)")
    logger.info("=" * 60)
    
    while True:
        try:
            schedule = get_posting_schedule()
            max_posts = schedule["max_posts"]
            posted_count = 0
            
            logger.info(f"\n📊 Cycle started: {schedule['name']} mode | Max posts: {max_posts}")
            
            # Process each category
            for category, sources in NEWS_SOURCES.items():
                if posted_count >= max_posts:
                    break
                
                for source in sources:
                    if posted_count >= max_posts:
                        break
                    
                    try:
                        # Fetch RSS feed
                        feed = await fetch_rss(source["rss"])
                        if not feed or not feed.entries:
                            continue
                        
                        # Get latest entry
                        entry = feed.entries[0]
                        article_id = generate_article_id(entry.title, entry.link)
                        
                        # Check if already posted
                        if await is_posted(article_id):
                            continue
                        
                        # Extract article data
                        article = {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": BeautifulSoup(
                                entry.get("summary", "") or entry.get("description", ""),
                                "html.parser"
                            ).get_text(strip=True)[:1500],
                            "image_url": extract_image(entry, source["url"]),
                            "source": source["name"],
                            "category": category
                        }
                        
                        logger.info(f"🔄 Processing: {article['title'][:60]}...")
                        
                        # Translate to Khmer
                        article = await translate_with_gemini(article)
                        
                        # Format post
                        message = format_facebook_post(article)
                        
                        # Post to Facebook
                        fb_post_id = await post_to_facebook(article, message)
                        
                        if fb_post_id:
                            await mark_as_posted(article_id, category, source["name"], fb_post_id)
                            posted_count += 1
                            stats['total_posts'] += 1
                            logger.info(f"✅ Posted ({posted_count}/{max_posts}): {article['title_kh'][:50]}...")
                            
                            # Delay between posts
                            await asyncio.sleep(10)
                        
                    except Exception as e:
                        logger.error(f"❌ Error processing {source['name']}: {str(e)[:200]}")
                        stats['errors'] += 1
            
            logger.info(f"\n✅ Cycle complete: {posted_count} posts published")
            logger.info(f"📊 Stats: Total={stats['total_posts']} Success={stats['successful_posts']} Failed={stats['failed_posts']}")
            logger.info(f"⏳ Next cycle in {CHECK_INTERVAL}s\n")
            
            await asyncio.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logger.critical(f"🔴 Worker crashed: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes before retry

# =========================== WEB SERVER ===========================
async def health_check(request):
    """Health check endpoint"""
    return web.json_response({
        "status": "✅ ALIVE",
        "bot": "Facebook News Bot",
        "page": FB_PAGE_NAME,
        "uptime": stats['start_time'],
        "stats": stats,
        "timestamp": datetime.now(ICT).isoformat()
    })

async def ping(request):
    """Simple ping endpoint"""
    return web.Response(text="OK")

async def web_server():
    """Start web server for health checks"""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    app.router.add_get("/ping", ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    logger.info(f"🌐 Web server started on port {PORT}")

# =========================== MAIN ENTRY POINT ===========================
async def main():
    """Main entry point"""
    await asyncio.gather(
        web_server(),
        worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped by user")
    except Exception as e:
        logger.critical(f"💥 Fatal error: {e}")