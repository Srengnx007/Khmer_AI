import asyncio
import json
import hashlib
import re
import logging
import traceback
from datetime import datetime, timedelta
from urllib.parse import urljoin
from collections import deque

import aiohttp
import feedparser
import backoff
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
from aiohttp import web

import config
import db

# =========================== LOGGING (JSON) ===========================
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(config.ICT).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module
        }
        if record.exc_info:
            log_obj["exception"] = traceback.format_exception(*record.exc_info)
        return json.dumps(log_obj)

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
        timestamp = datetime.now(config.ICT).strftime("%H:%M:%S")
        BOT_STATE["logs"].appendleft(f"[{timestamp}] {record.getMessage()}")

logger = logging.getLogger("KhmerNewsBot")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.addHandler(DashboardHandler())

# =========================== AI CONFIG ===========================
if config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

trigger_event = asyncio.Event()

# =========================== FETCHING ===========================
@backoff.on_exception(backoff.expo, (aiohttp.ClientError, asyncio.TimeoutError), max_tries=3)
async def fetch_rss(url: str):
    headers = {"User-Agent": "KhmerNewsBot/2.0 (+https://t.me/AIDailyNewsKH)"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as s:
        async with s.get(url) as r:
            if r.status == 200: return feedparser.parse(await r.text())
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
    try:
        return hashlib.md5(f"{t}{l}".encode()).hexdigest()
    except Exception:
        return str(hash(f"{t}{l}"))

# =========================== TRANSLATION (CACHED) ===========================
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
async def translate(article):
    # Check Cache
    aid = await get_article_id(article['title'], article['link'])
    cached = await db.get_translation(aid)
    if cached:
        article["title_kh"] = cached["title_kh"]
        article["body_kh"] = cached["body_kh"]
        return article

    prompt = f"Translate to natural, engaging Khmer for Telegram news:\nTitle: {article['title']}\nContent: {article['summary'][:2500]}\nReturn JSON: {{\"title_kh\": \"...\", \"body_kh\": \"...\"}}"
    try:
        model = genai.GenerativeModel(config.GEMINI_MODEL)
        resp = await asyncio.to_thread(
            model.generate_content, 
            prompt, 
            safety_settings=SAFETY_SETTINGS
        )
        
        text = resp.text.strip()
        text = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1: text = text[start:end]
            
        data = json.loads(text)
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        
        # Save to Cache
        await db.save_translation(aid, article["title_kh"], article["body_kh"])
        await asyncio.sleep(7)
        
    except Exception as e:
        logger.warning(f"Translation Error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
    return article

# =========================== POSTING ===========================
@backoff.on_exception(backoff.expo, Exception, max_tries=3)
async def post_to_facebook(article: dict, emoji: str):
    if not (config.FB_PAGE_ID and config.FB_ACCESS_TOKEN): 
        logger.error("❌ FB Error: Credentials missing!")
        return False
    
    message = f"{emoji} {article['title_kh']}\n\n{article['body_kh']}\n\n__________________\nប្រភព: {article['source']}\n👉 តាមដាន Telegram: {config.TG_LINK_FOR_FB}\nអានបន្ថែម: {article['link']}"
    api_ver = getattr(config, "FB_API_VERSION", "v19.0")

    async with aiohttp.ClientSession() as s:
        # 1. Try Photo
        if article.get("image_url"):
            url = f"https://graph.facebook.com/{api_ver}/{config.FB_PAGE_ID}/photos"
            params = {"url": article["image_url"], "message": message, "access_token": config.FB_ACCESS_TOKEN, "published": "true"}
            async with s.post(url, data=params) as r:
                resp_data = await r.json()
                if resp_data.get("id"): 
                    BOT_STATE["fb_posts"] += 1
                    logger.info(f"✅ FB PHOTO Posted: {resp_data.get('id')}")
                    return True

        # 2. Link Fallback
        url = f"https://graph.facebook.com/{api_ver}/{config.FB_PAGE_ID}/feed"
        params = {"link": article["link"], "message": message, "access_token": config.FB_ACCESS_TOKEN, "published": "true"}
        async with s.post(url, data=params) as r:
            resp_data = await r.json()
            if resp_data.get("id"): 
                BOT_STATE["fb_posts"] += 1
                logger.info(f"✅ FB Link Posted: {resp_data.get('id')}")
                return True
    return False

@backoff.on_exception(backoff.expo, (NetworkError, TimedOut), max_tries=3)
async def post_to_telegram(article: dict, emoji: str, is_breaking: bool = False):
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID): return False
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    
    title_prefix = ""
    if any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("thai", [])): title_prefix = "🇹🇭 "
    elif any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("vietnamese", [])): title_prefix = "🇻🇳 "

    caption = (
        f"{emoji} {title_prefix}<b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"ប្រភព: {article['source']}\n"
        f"🔗 Link: {article['link']}\n"
        f"{datetime.now(config.ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📰", url=article["link"])],
        [InlineKeyboardButton("Facebook Page 📘", url=config.FB_LINK_FOR_TG)]
    ])

    msg = None
    if article.get("image_url"):
        async with aiohttp.ClientSession() as s:
            async with s.get(article["image_url"], timeout=10) as r:
                if r.status == 200:
                    msg = await bot.send_photo(chat_id=config.TELEGRAM_CHANNEL_ID, photo=await r.read(), caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=buttons)

    if not msg:
        msg = await bot.send_message(chat_id=config.TELEGRAM_CHANNEL_ID, text=caption, parse_mode=ParseMode.HTML, reply_markup=buttons, disable_web_page_preview=False)
    
    if msg:
        BOT_STATE["tg_posts"] += 1
        if is_breaking:
            try:
                await bot.pin_chat_message(chat_id=config.TELEGRAM_CHANNEL_ID, message_id=msg.message_id)
                logger.info("📌 Breaking News Pinned!")
            except Exception as e:
                logger.warning(f"Pin Failed: {e}")
        return True
    return False

# =========================== WORKER ===========================
async def worker():
    await db.init_db()
    logger.info("🚀 MEGA NEWS BOT 2026 STARTED")
    boost_until = None
    
    while True:
        try:
            BOT_STATE["last_run"] = datetime.now(config.ICT).strftime("%H:%M:%S")
            now = datetime.now(config.ICT)
            slot = config.get_current_slot()

            if trigger_event.is_set():
                logger.info("⚡ Manual Trigger Executing!")
                trigger_event.clear()
                max_posts = 10
            elif boost_until and now < boost_until:
                max_posts = 15
                logger.info("🔥 BOOST ACTIVE")
            else:
                max_posts = max(1, slot["max"] // 4)
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
                for src in config.NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts: break
                    try:
                        feed = await fetch_rss(src["rss"])
                        if not feed or not feed.entries: continue
                        
                        e = feed.entries[0]
                        aid = await get_article_id(e.title, e.link)
                        if await db.is_posted(aid): continue

                        article = {
                            "title": e.title, "link": e.link,
                            "summary": BeautifulSoup(e.get("summary",""), "html.parser").get_text(strip=True)[:1000],
                            "image_url": get_image(e, src["url"]),
                            "source": src["name"]
                        }
                        
                        is_breaking = False
                        if config.is_breaking_news(article) and not boost_until:
                            logger.info("🚨 BREAKING DETECTED -> BOOST ON")
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + emoji 
                            is_breaking = True
                        
                        article = await translate(article)

                        fb_ok = await post_to_facebook(article, emoji)
                        tg_ok = await post_to_telegram(article, emoji, is_breaking)

                        if fb_ok or tg_ok:
                            await db.mark_as_posted(aid, cat, src["name"])
                            posted_count += 1
                            BOT_STATE["total_posted"] += 1
                            logger.info(f"✅ Posted: {article['title_kh'][:30]}")
                            if boost_until: await asyncio.sleep(5)
                            else: await asyncio.sleep(slot["delay"])

                    except Exception as e:
                        logger.error(f"Err {src['name']}: {e}")
                        BOT_STATE["errors"] += 1

            next_wait = 60 if boost_until else slot["delay"]
            next_time = (datetime.now(config.ICT) + timedelta(seconds=next_wait)).strftime("%H:%M:%S")
            BOT_STATE["next_run"] = next_time
            BOT_STATE["status"] = "Sleeping"
            logger.info(f"Cycle done. Posts: {posted_count}. Next: {next_time}")
            
            try:
                await asyncio.wait_for(trigger_event.wait(), timeout=next_wait)
            except asyncio.TimeoutError:
                pass 

        except Exception as e:
            logger.error(f"Loop error: {e}")
            await asyncio.sleep(60)

# =========================== SERVER ===========================
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Khmer News Bot 2026</title>
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
        <h1>🤖 Khmer News Bot 2026</h1>
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
    return web.Response(text="Check Triggered!", content_type='text/html')

async def health_check(request):
    return web.Response(text="OK", status=200)

async def metrics(request):
    return web.json_response(BOT_STATE)

async def web_server():
    app = web.Application()
    app.router.add_get("/", dashboard)
    app.router.add_post("/trigger", trigger_check)
    app.router.add_get("/health", health_check)
    app.router.add_get("/metrics", metrics)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logger.info(f"🌐 Server live on port {config.PORT}")

async def main(): await asyncio.gather(web_server(), worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.critical(f"💥 FATAL CRASH:\n{traceback.format_exc()}")
