# bot.py – Khmer News Bot 2026 (Master Edition)
# Features: 
# - Massive Sources (Cambodia, ASEAN, World, Tech, Crypto)
# - Facebook & Telegram Cross-Posting with Smart Links
# - Breaking News Boost Logic (1-min check)
# - Dynamic Scheduling (Time-based)
# - Database Protection (SQLite)
# - Web Dashboard UI

import os
import asyncio
import json
import hashlib
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin
from collections import deque

import pytz
from dotenv import load_dotenv
import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from aiohttp import web
import aiosqlite

# =========================== CONFIGURATION ===========================
load_dotenv()

# 1. Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TG_LINK_FOR_FB = "https://t.me/AIDailyNewsKH"

# 2. Facebook Settings
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
FB_LINK_FOR_TG = "https://www.facebook.com/profile.php?id=61584116626111"

# 3. AI Settings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# ប្រើ gemini-2.0-flash ឬ gemini-1.5-flash-001
GEMINI_MODEL = "gemini-2.0-flash" 
CHECK_INTERVAL = 900  # 15 minutes normal cycle

# 4. System Settings
ICT = pytz.timezone('Asia/Phnom_Penh')
DB_FILE = "posted_articles.db"
db_lock = asyncio.Lock()
PORT = int(os.environ.get("PORT", 8080))

# 5. Dashboard State
BOT_STATE = {
    "status": "Starting...",
    "last_run": "Never",
    "next_run": "Calculating...",
    "total_posted": 0,
    "fb_posts": 0,
    "tg_posts": 0,
    "errors": 0,
    "logs": deque(maxlen=50)
}

class DashboardHandler(logging.Handler):
    def emit(self, record):
        timestamp = datetime.now(ICT).strftime("%H:%M:%S")
        BOT_STATE["logs"].appendleft(f"[{timestamp}] {self.format(record)}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), DashboardHandler()]
)
logger = logging.getLogger(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

trigger_event = asyncio.Event()

# =========================== MASSIVE RSS SOURCES ===========================
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
        {"name": "Thai PBS",       "rss": "https://english.thaipbs.or.th/feed",              "url": "https://english.thaipbs.or.th"},
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

# =========================== CORE LOGIC ===========================
def get_current_slot():
    now = datetime.now(ICT)
    h = now.hour + now.minute / 60
    if 5 <= h < 8:       return {"name": "Morning 🌅",      "max": 8}
    if 8 <= h < 11.5:    return {"name": "Work AM 💼",      "max": 5}
    if 11.5 <= h < 13.5: return {"name": "Lunch Peak 🍱",   "max": 8}
    if 13.5 <= h < 17:   return {"name": "Afternoon ☕",    "max": 5}
    if 17 <= h < 21:     return {"name": "Prime Time 📺",   "max": 10}
    if 21 <= h < 23:     return {"name": "Night 🌙",        "max": 4}
    return                       {"name": "Deep Night 💤",   "max": 1}

def is_breaking_news(article):
    score = 0
    title = article['title'].lower()
    kws = ["breaking", "urgent", "shooting", "explosion", "crash", "dead", "crisis", "war", 
           "បន្ទាន់", "ភ្លាម", "បាញ់", "ផ្ទុះ", "ស្លាប់", "គ្រោះថ្នាក់", "រញ្ជួយដី"]
    for w in kws:
        if w in title: score += 100
    if "!" in title: score += 10
    
    if article['source'] in ["Khmer Times", "BBC News", "CNN", "Thmey Thmey"]: score += 20
    
    return score >= 100

# =========================== DATABASE ===========================
async def init_db():
    async with db_lock:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS posted (
                    article_id TEXT PRIMARY KEY,
                    category TEXT,
                    source TEXT,
                    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
    logger.info("✅ Database initialized")

async def is_posted(aid: str) -> bool:
    async with db_lock:
        async with aiosqlite.connect(DB_FILE) as db:
            cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
            return await cur.fetchone() is not None

async def mark_as_posted(aid: str, cat: str, source: str):
    async with db_lock:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("INSERT OR IGNORE INTO posted(article_id, category, source) VALUES(?, ?, ?)", (aid, cat, source))
            await db.commit()

# =========================== FETCHING & PROCESSING ===========================
async def fetch_rss(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as s:
        try:
            async with s.get(url) as r:
                if r.status == 200: return feedparser.parse(await r.text())
        except: pass
    return None

def get_image(entry, base_url: str):
    try:
        if hasattr(entry, "media_content") and entry.media_content: return entry.media_content[0].get("url")
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail: return entry.media_thumbnail[0].get("url")
        soup = BeautifulSoup(entry.get("summary","") or entry.get("description",""), "html.parser")
        img = soup.find("img")
        if img:
            src = img.get("src")
            if src and not src.startswith("http"):
                return urljoin(base_url, src)
            return src
    except: pass
    return None

async def get_article_id(t: str, l: str):
    return hashlib.md5(f"{t}{l}".encode()).hexdigest()

async def translate(article):
    prompt = f"Translate to natural Khmer:\nTitle: {article['title']}\nContent: {article['summary'][:2500]}\nReturn JSON: {{\"title_kh\": \"...\", \"body_kh\": \"...\"}}"
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = await asyncio.to_thread(model.generate_content, prompt)
        
        # Robust JSON Cleaning
        text = resp.text.strip()
        text = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1: text = text[start:end]
            
        data = json.loads(text)
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        await asyncio.sleep(5)
    except Exception as e:
        logger.warning(f"Translation Error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
    return article

# =========================== POSTING ===========================
async def post_to_facebook(article: dict, emoji: str):
    if not (FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN): return False
    message = f"{emoji} {article['title_kh']}\n\n{article['body_kh']}\n\n__________________\nប្រភព: {article['source']}\n👉 តាមដាន Telegram: {TG_LINK_FOR_FB}\nអានបន្ថែម: {article['link']}"
    try:
        async with aiohttp.ClientSession() as s:
            if article.get("image_url"):
                url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
                params = {"url": article["image_url"], "message": message, "access_token": FACEBOOK_ACCESS_TOKEN, "published": "true"}
                async with s.post(url, data=params) as r:
                    if (await r.json()).get("id"): 
                        BOT_STATE["fb_posts"] += 1
                        return True
            
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
            params = {"link": article["link"], "message": message, "access_token": FACEBOOK_ACCESS_TOKEN, "published": "true"}
            async with s.post(url, data=params) as r:
                if (await r.json()).get("id"): 
                    BOT_STATE["fb_posts"] += 1
                    return True
    except: pass
    return False

async def post_to_telegram(article: dict, emoji: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID): return False
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # ✅ Link added to caption here
    caption = (
        f"{emoji} <b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"ប្រភព: {article['source']}\n"
        f"🔗 Link: {article['link']}\n"
        f"{datetime.now(ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📰", url=article["link"])],
        [InlineKeyboardButton("Facebook Page 📘", url=FB_LINK_FOR_TG)]
    ])
    try:
        if article.get("image_url"):
            async with aiohttp.ClientSession() as s:
                async with s.get(article["image_url"], timeout=10) as r:
                    if r.status == 200:
                        await bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=await r.read(), caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=buttons)
                        BOT_STATE["tg_posts"] += 1
                        return True
        await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=caption, parse_mode=ParseMode.HTML, reply_markup=buttons, disable_web_page_preview=False)
        BOT_STATE["tg_posts"] += 1
        return True
    except Exception:
        BOT_STATE["errors"] += 1
        return False

# =========================== WORKER LOOP ===========================
async def worker():
    await init_db()
    logging.info("🚀 MEGA NEWS BOT STARTED (Master Edition)")
    boost_until = None
    
    while True:
        try:
            BOT_STATE["last_run"] = datetime.now(ICT).strftime("%H:%M:%S")
            now = datetime.now(ICT)
            slot = get_current_slot()

            if trigger_event.is_set():
                logging.info("⚡ Manual Trigger Executing!")
                trigger_event.clear()
                max_posts = 10
            elif boost_until and now < boost_until:
                max_posts = 15
                delay = 60
                logging.info("🔥 BOOST ACTIVE (Fast Mode)")
            else:
                max_posts = max(1, slot["max"] // 4)
                delay = CHECK_INTERVAL
                boost_until = None

            BOT_STATE["status"] = f"Processing ({slot['name']})"
            posted_count = 0
            
            categories = [
                ("cambodia", "🇰🇭"), ("international", "🌍"), 
                ("thai", "🇹🇭"), ("vietnamese", "🇻🇳"), 
                ("china", "🇨🇳"), ("tech", "💻"), ("crypto", "₿")
            ]

            for cat, emoji in categories:
                if posted_count >= max_posts: break
                for src in NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts: break
                    try:
                        feed = await fetch_rss(src["rss"])
                        if not feed or not feed.entries: continue
                        
                        e = feed.entries[0]
                        aid = await get_article_id(e.title, e.link)
                        if await is_posted(aid): continue

                        article = {
                            "title": e.title, "link": e.link,
                            "summary": BeautifulSoup(e.get("summary",""), "html.parser").get_text(strip=True)[:1000],
                            "image_url": get_image(e, src["url"]),
                            "source": src["name"]
                        }
                        
                        if is_breaking_news(article) and not boost_until:
                            logging.info("🚨 BREAKING DETECTED -> BOOST ON")
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + emoji 
                        
                        article = await translate(article)

                        fb_ok = await post_to_facebook(article, emoji)
                        tg_ok = await post_to_telegram(article, emoji)

                        if fb_ok or tg_ok:
                            await mark_as_posted(aid, cat, src["name"])
                            posted_count += 1
                            BOT_STATE["total_posted"] += 1
                            logging.info(f"✅ Posted: {article['title_kh'][:30]}")
                            if boost_until: await asyncio.sleep(5)
                            else: await asyncio.sleep(15)

                    except Exception as e:
                        logging.error(f"Err {src['name']}: {e}")
                        BOT_STATE["errors"] += 1

            next_wait = 60 if boost_until else CHECK_INTERVAL
            next_time = (datetime.now(ICT) + timedelta(seconds=next_wait)).strftime("%H:%M:%S")
            BOT_STATE["next_run"] = next_time
            BOT_STATE["status"] = "Sleeping"
            logging.info(f"Cycle done. Posts: {posted_count}. Next: {next_time}")
            
            try:
                await asyncio.wait_for(trigger_event.wait(), timeout=next_wait)
            except asyncio.TimeoutError:
                pass 

        except Exception as e:
            logging.error(f"Loop error: {e}")
            await asyncio.sleep(60)

# =========================== DASHBOARD ===========================
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Khmer News Bot</title>
    <meta http-equiv="refresh" content="30">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: sans-serif; background: #121212; color: #fff; padding: 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        h1 {{ text-align: center; color: #4CAF50; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }}
        .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; text-align: center; }}
        .card h3 {{ margin: 0; font-size: 2em; color: #2196F3; }}
        .btn {{ width: 100%; padding: 15px; background: #E91E63; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 1.2em; }}
        .log-box {{ background: #000; padding: 10px; height: 300px; overflow-y: auto; font-family: monospace; border: 1px solid #333; }}
        .log-entry {{ border-bottom: 1px solid #222; padding: 2px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Khmer News Bot Dashboard</h1>
        <form action="/trigger" method="post"><button class="btn">⚡ Trigger Check Now</button></form>
        <div class="card" style="margin-top: 20px; text-align: left;">
            <div><strong>Status:</strong> {status}</div>
            <div><strong>Last Run:</strong> {last_run}</div>
            <div><strong>Next Run:</strong> {next_run}</div>
        </div>
        <div class="grid">
            <div class="card"><h3>{total_posted}</h3><p>Total Posts</p></div>
            <div class="card"><h3>{fb_posts}</h3><p>Facebook</p></div>
            <div class="card"><h3>{tg_posts}</h3><p>Telegram</p></div>
            <div class="card"><h3 style="color:red">{errors}</h3><p>Errors</p></div>
        </div>
        <h3>📜 Live Logs</h3>
        <div class="log-box">{logs}</div>
    </div>
</body>
</html>
"""

async def dashboard(request):
    logs_html = "".join([f"<div class='log-entry'>{l}</div>" for l in BOT_STATE["logs"]])
    return web.Response(text=HTML.format(
        status=BOT_STATE["status"],
        last_run=BOT_STATE["last_run"],
        next_run=BOT_STATE["next_run"],
        total_posted=BOT_STATE["total_posted"],
        fb_posts=BOT_STATE["fb_posts"],
        tg_posts=BOT_STATE["tg_posts"],
        errors=BOT_STATE["errors"],
        logs=logs_html
    ), content_type='text/html')

async def trigger_check(request):
    trigger_event.set()
    return web.Response(text="Check Triggered! <a href='/'>Go Back</a>", content_type='text/html')

async def web_server():
    app = web.Application()
    app.router.add_get("/", dashboard)
    app.router.add_post("/trigger", trigger_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()
    logging.info("🌐 Server live on port 8080")

async def main(): await asyncio.gather(web_server(), worker())

if __name__ == "__main__": asyncio.run(main())