import asyncio
import json
import hashlib
import re
import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin
from collections import deque

import aiohttp
import feedparser
from bs4 import BeautifulSoup
import google.generativeai as genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
from aiohttp import web
import traceback

import config
import db

# =========================== LOGGING & STATE ===========================
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
        BOT_STATE["logs"].appendleft(f"[{timestamp}] {self.format(record)}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), DashboardHandler()]
)
logger = logging.getLogger(__name__)

if config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)

trigger_event = asyncio.Event()

# =========================== FETCHING & PROCESSING ===========================
async def fetch_rss(url: str):
    headers = {"User-Agent": "KhmerNewsBot/2.0 (+https://t.me/AIDailyNewsKH)"}
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
    try:
        return hashlib.md5(f"{t}{l}".encode()).hexdigest()
    except Exception:
        return str(hash(f"{t}{l}"))

async def translate(article):
    prompt = f"Translate to natural, engaging Khmer for Telegram news:\nTitle: {article['title']}\nContent: {article['summary'][:2500]}\nReturn JSON: {{\"title_kh\": \"...\", \"body_kh\": \"...\"}}"
    try:
        model = genai.GenerativeModel(config.GEMINI_MODEL)
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
        await asyncio.sleep(7)
    except Exception as e:
        logger.warning(f"Translation Error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
    return article

# =========================== POSTING ===========================
async def post_to_facebook(article: dict, emoji: str):
    if not (config.FB_PAGE_ID and config.FB_ACCESS_TOKEN): 
        logger.error("❌ FB Error: Credentials missing!")
        return False
    
    message = f"{emoji} {article['title_kh']}\n\n{article['body_kh']}\n\n__________________\nប្រភព: {article['source']}\n👉 តាមដាន Telegram: {config.TG_LINK_FOR_FB}\nអានបន្ថែម: {article['link']}"

    try:
        async with aiohttp.ClientSession() as s:
            # 1. Try Photo
            if article.get("image_url"):
                url = f"https://graph.facebook.com/v19.0/{config.FB_PAGE_ID}/photos"
                params = {"url": article["image_url"], "message": message, "access_token": config.FB_ACCESS_TOKEN, "published": "true"}
                async with s.post(url, data=params) as r:
                    resp_data = await r.json()
                    if resp_data.get("id"): 
                        BOT_STATE["fb_posts"] += 1
                        logger.info(f"✅ FB PHOTO Posted: {resp_data.get('id')}")
                        return True
                    else:
                        logger.error(f"❌ FB Photo Failed (Response): {resp_data.get('error', 'Unknown Error')}")

            # 2. Link Fallback
            url = f"https://graph.facebook.com/v19.0/{config.FB_PAGE_ID}/feed"
            params = {"link": article["link"], "message": message, "access_token": config.FB_ACCESS_TOKEN, "published": "true"}
            async with s.post(url, data=params) as r:
                resp_data = await r.json()
                if resp_data.get("id"): 
                    BOT_STATE["fb_posts"] += 1
                    logger.info(f"✅ FB Link Posted: {resp_data.get('id')}")
                    return True
                else:
                    logger.error(f"❌ FB Link Failed (Response): {resp_data.get('error', 'Unknown Error')}")

    except Exception as e:
        logger.error(f"❌ FB EXCEPTION: {e}")
        
    return False

async def post_to_telegram(article: dict, emoji: str):
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHANNEL_ID): return False
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    
    # Add Flag Emoji based on source
    title_prefix = ""
    if any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("thai", [])):
        title_prefix = "🇹🇭 "
    elif any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("vietnamese", [])):
        title_prefix = "🇻🇳 "

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
    try:
        if article.get("image_url"):
            async with aiohttp.ClientSession() as s:
                async with s.get(article["image_url"], timeout=10) as r:
                    if r.status == 200:
                        photo_data = await r.read()
                        for attempt in range(3):
                            try:
                                await bot.send_photo(chat_id=config.TELEGRAM_CHANNEL_ID, photo=photo_data, caption=caption[:1024], parse_mode=ParseMode.HTML, reply_markup=buttons)
                                BOT_STATE["tg_posts"] += 1
                                return True
                            except (NetworkError, TimedOut) as e:
                                logger.warning(f"⚠️ TG Photo Retry {attempt+1}/3: {e}")
                                await asyncio.sleep(2)
                        return False

        for attempt in range(3):
            try:
                await bot.send_message(chat_id=config.TELEGRAM_CHANNEL_ID, text=caption, parse_mode=ParseMode.HTML, reply_markup=buttons, disable_web_page_preview=False)
                BOT_STATE["tg_posts"] += 1
                return True
            except (NetworkError, TimedOut) as e:
                logger.warning(f"⚠️ TG Message Retry {attempt+1}/3: {e}")
                await asyncio.sleep(2)
        return False

    except Exception as e:
        logger.error(f"❌ TG Error: {e}")
        BOT_STATE["errors"] += 1
        return False

# =========================== WORKER LOOP ===========================
async def worker():
    await db.init_db()
    logging.info("🚀 MEGA NEWS BOT STARTED (Master Edition)")
    boost_until = None
    
    while True:
        try:
            BOT_STATE["last_run"] = datetime.now(config.ICT).strftime("%H:%M:%S")
            now = datetime.now(config.ICT)
            slot = config.get_current_slot()

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
                delay = config.CHECK_INTERVAL
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
                        
                        if config.is_breaking_news(article) and not boost_until:
                            logging.info("🚨 BREAKING DETECTED -> BOOST ON")
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + emoji 
                        
                        article = await translate(article)

                        fb_ok = await post_to_facebook(article, emoji)
                        tg_ok = await post_to_telegram(article, emoji)

                        if fb_ok or tg_ok:
                            await db.mark_as_posted(aid, cat, src["name"])
                            posted_count += 1
                            BOT_STATE["total_posted"] += 1
                            logging.info(f"✅ Posted: {article['title_kh'][:30]}")
                            if boost_until: await asyncio.sleep(5)
                            else: await asyncio.sleep(slot["delay"])

                    except Exception as e:
                        logging.error(f"Err {src['name']}: {e}")
                        BOT_STATE["errors"] += 1

            next_wait = 60 if boost_until else config.CHECK_INTERVAL
            next_time = (datetime.now(config.ICT) + timedelta(seconds=next_wait)).strftime("%H:%M:%S")
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
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logging.info(f"🌐 Server live on port {config.PORT}")

async def main(): await asyncio.gather(web_server(), worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.critical(f"💥 FATAL CRASH:\n{traceback.format_exc()}")
