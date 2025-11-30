import asyncio
import json
import hashlib
import re
import logging
import traceback
import time
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

# =========================== LOGGING ===========================
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
        return json.dumps(log_obj, ensure_ascii=False)

BOT_STATE = {
    "status": "Starting...",
    "last_run": "Never",
    "next_run": "Calculating...",
    "total_posted": 0,
    "fb_posts": 0,
    "tg_posts": 0,
    "errors": 0,
    "translations": 0,
    "cache_hits": 0,
    "logs": deque(maxlen=50)
}

class DashboardHandler(logging.Handler):
    def emit(self, record):
        timestamp = datetime.now(config.ICT).strftime("%H:%M:%S")
        BOT_STATE["logs"].appendleft(f"[{timestamp}] {record.levelname} - {record.getMessage()}")

logger = logging.getLogger("KhmerNewsBot")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.addHandler(DashboardHandler())

# =========================== SINGLETONS ===========================

# Telegram Bot (singleton)
telegram_bot = None
if config.TELEGRAM_BOT_TOKEN:
    telegram_bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    logger.info("✅ Telegram bot initialized")

# Gemini AI
if config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)
    logger.info("✅ Gemini AI configured")

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Global state
trigger_event = asyncio.Event()
boost_until = None

# Rate limiting
gemini_calls = deque(maxlen=60)

# =========================== RATE LIMITER ===========================

async def check_rate_limit():
    """Ensure we don't exceed Gemini rate limits (15/min)"""
    now = time.time()
    
    # Remove calls older than 1 minute
    while gemini_calls and now - gemini_calls[0] > 60:
        gemini_calls.popleft()
    
    # If at limit, wait
    if len(gemini_calls) >= 15:
        wait_time = 60 - (now - gemini_calls[0]) + 1
        logger.warning(f"⏳ Rate limit reached, waiting {wait_time:.1f}s")
        await asyncio.sleep(wait_time)
    
    gemini_calls.append(now)

# =========================== ERROR REPORTING ===========================

async def send_error_report(subject: str, message: str, extra_context: dict = None):
    """Send error report to Telegram"""
    target_id = config.TELEGRAM_LOG_CHANNEL_ID or config.TELEGRAM_PERSONAL_ID
    if not (telegram_bot and target_id): 
        return

    context_str = ""
    if extra_context:
        context_str = "\n\n📊 Context:\n" + "\n".join([f"• {k}: {v}" for k, v in extra_context.items()])
    
    text = f"🚨 <b>{subject}</b>\n\n<pre>{message[:2000]}</pre>{context_str}"
    
    try:
        await telegram_bot.send_message(
            chat_id=target_id, 
            text=text[:4096], 
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Failed to send error report: {e}")

# =========================== FETCHING ===========================

@backoff.on_exception(backoff.expo, (aiohttp.ClientError, asyncio.TimeoutError), max_tries=3)
async def fetch_rss(url: str):
    """Fetch RSS feed with retry"""
    headers = {"User-Agent": "KhmerNewsBot/2.0 (+https://t.me/AIDailyNewsKH)"}
    
    async with aiohttp.ClientSession(
        headers=headers, 
        timeout=aiohttp.ClientTimeout(total=25)
    ) as session:
        async with session.get(url) as response:
            if response.status == 200:
                return feedparser.parse(await response.text())
    
    return None


def get_image(entry, base_url: str):
    """Extract image URL from RSS entry"""
    try:
        # Try media:content
        if hasattr(entry, "media_content") and entry.media_content:
            return entry.media_content[0].get("url")
        
        # Try media:thumbnail
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            return entry.media_thumbnail[0].get("url")
        
        # Parse HTML
        html = entry.get("summary", "") or entry.get("description", "")
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        
        if img:
            src = img.get("src")
            if src:
                if not src.startswith("http"):
                    return urljoin(base_url, src)
                return src
    except Exception as e:
        logger.debug(f"Image extraction error: {e}")
    
    return None


async def validate_image(image_url: str) -> bool:
    """Validate image URL is accessible and valid"""
    if not image_url:
        return False
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(image_url, timeout=5) as response:
                # Check content type
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    return False
                
                # Check size (max 20MB for Telegram)
                content_length = int(response.headers.get('Content-Length', 0))
                if content_length > 20 * 1024 * 1024:
                    return False
                
                return response.status == 200
    except:
        return False


async def get_article_id(title: str, link: str):
    """Generate unique article ID"""
    try:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()
    except Exception:
        return str(hash(f"{title}{link}"))

# =========================== TRANSLATION ===========================

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
async def translate(article):
    """Translate article to Khmer with caching"""
    aid = await get_article_id(article['title'], article['link'])
    
    # Check cache first
    cached = await db.get_translation(aid)
    if cached:
        article["title_kh"] = cached["title_kh"]
        article["body_kh"] = cached["body_kh"]
        BOT_STATE["cache_hits"] += 1
        logger.debug(f"✅ Cache hit for: {article['title'][:30]}")
        return article
    
    # Check rate limit before calling API
    await check_rate_limit()
    
    prompt = f"""Translate to natural, engaging Khmer for Telegram news:

Title: {article['title']}
Content: {article['summary'][:2500]}

Return ONLY valid JSON with no markdown:
{{"title_kh": "...", "body_kh": "..."}}"""

    try:
        model = genai.GenerativeModel(config.GEMINI_MODEL)
        
        response = await asyncio.to_thread(
            model.generate_content, 
            prompt, 
            safety_settings=SAFETY_SETTINGS
        )
        
        text = response.text.strip()
        
        # Clean markdown
        text = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
        
        # Extract JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1:
            text = text[start:end]
        
        data = json.loads(text)
        
        article["title_kh"] = data.get("title_kh", article["title"])
        article["body_kh"] = data.get("body_kh", article["summary"][:500])
        
        # Save to cache
        await db.save_translation(aid, article["title_kh"], article["body_kh"])
        
        BOT_STATE["translations"] += 1
        logger.info(f"✅ Translated: {article['title'][:30]}")
        
        # Rate limiting delay
        await asyncio.sleep(7)
        
    except json.JSONDecodeError as e:
        logger.warning(f"⚠️ JSON parse error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        BOT_STATE["errors"] += 1
        
    except Exception as e:
        logger.error(f"❌ Translation error: {e}")
        article["title_kh"] = article["title"]
        article["body_kh"] = article["summary"][:500]
        BOT_STATE["errors"] += 1
        
        await send_error_report(
            "Translation Failed",
            str(e),
            extra_context={
                'article_id': aid,
                'source': article['source'],
                'title': article['title'][:50]
            }
        )
    
    return article

# =========================== POSTING ===========================

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
async def post_to_x(article: dict, emoji: str):
    if not (config.X_API_KEY and config.X_API_SECRET and config.X_ACCESS_TOKEN and config.X_ACCESS_TOKEN_SECRET):
        return False

    # Truncate to 280 chars
    msg = f"{emoji} {article['title_kh']}\n{article['link']}"
    if len(msg) > 280:
        msg = msg[:277] + "..."

    try:
        # Placeholder for https://api.twitter.com/2/tweets
        # Real OAuth1.0a/OAuth2.0 logic omitted for structure
        logger.info(f"✅ X Post (Simulated) to https://api.twitter.com/2/tweets: {msg[:50]}...")
        return True
    except Exception as e:
        logger.error(f"X Post Failed: {e}")
        return False

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
async def post_to_facebook(article: dict, emoji: str):
    """Post article to Facebook Page"""
    if not (config.FB_PAGE_ID and config.FB_ACCESS_TOKEN):
        logger.error("❌ FB Error: Credentials missing!")
        return False
    
    message = (
        f"{emoji} {article['title_kh']}\n\n"
        f"{article['body_kh']}\n\n"
        f"__________________\n"
        f"👉 Telegram: {config.TG_LINK_FOR_FB}\n"
        f"👉 Facebook: {config.FB_LINK_FOR_TG}\n"
        f"👉 X (Twitter): https://x.com/{config.X_USERNAME.strip('@')}"
    )
    
    api_ver = config.FB_API_VERSION
    
    async with aiohttp.ClientSession() as session:
        # Try photo first
        if article.get("image_url"):
            url = f"https://graph.facebook.com/{api_ver}/{config.FB_PAGE_ID}/photos"
            params = {
                "url": article["image_url"],
                "message": message,
                "access_token": config.FB_ACCESS_TOKEN,
                "published": "true"
            }
            
            async with session.post(url, data=params) as response:
                resp_data = await response.json()
                
                if resp_data.get("id"):
                    BOT_STATE["fb_posts"] += 1
                    logger.info(f"✅ FB Photo Posted: {resp_data.get('id')}")
                    return True
        
        # Fallback to link post
        url = f"https://graph.facebook.com/{api_ver}/{config.FB_PAGE_ID}/feed"
        params = {
            "link": article["link"],
            "message": message,
            "access_token": config.FB_ACCESS_TOKEN,
            "published": "true"
        }
        
        async with session.post(url, data=params) as response:
            resp_data = await response.json()
            
            if resp_data.get("id"):
                BOT_STATE["fb_posts"] += 1
                logger.info(f"✅ FB Link Posted: {resp_data.get('id')}")
                return True
    
    return False


@backoff.on_exception(backoff.expo, (NetworkError, TimedOut), max_tries=3)
async def post_to_telegram(article: dict, emoji: str, is_breaking: bool = False):
    """Post article to Telegram Channel"""
    if not (telegram_bot and config.TELEGRAM_CHANNEL_ID):
        return False
    
    # Add country flag prefix
    title_prefix = ""
    if any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("thai", [])):
        title_prefix = "🇹🇭 "
    elif any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("vietnamese", [])):
        title_prefix = "🇻🇳 "
    elif any(s["name"] == article["source"] for s in config.NEWS_SOURCES.get("china", [])):
        title_prefix = "🇨🇳 "
    
    caption = (
        f"{emoji} {title_prefix}<b>{article['title_kh']}</b>\n\n"
        f"{article['body_kh']}\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔗 Link: {article['link']}\n"
        f"X: {config.X_USERNAME}\n"
        f"{datetime.now(config.ICT):%d/%m/%Y • %H:%M}"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("អានពេញ 📰", url=article["link"])],
        [InlineKeyboardButton("Facebook Page 📘", url=config.FB_LINK_FOR_TG)],
        [InlineKeyboardButton("X (Twitter) 🐦", url=f"https://x.com/{config.X_USERNAME.strip('@')}")]
    ])
    
    msg = None
    
    # Try with photo
    if article.get("image_url"):
        # Validate image first
        if await validate_image(article["image_url"]):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(article["image_url"], timeout=10) as response:
                        if response.status == 200:
                            photo_data = await response.read()
                            msg = await telegram_bot.send_photo(
                                chat_id=config.TELEGRAM_CHANNEL_ID,
                                photo=photo_data,
                                caption=caption[:1024],
                                parse_mode=ParseMode.HTML,
                                reply_markup=buttons
                            )
            except Exception as e:
                logger.warning(f"⚠️ Photo send failed: {e}")
        else:
            logger.warning(f"⚠️ Invalid image: {article['image_url']}")
    
    # Fallback to text
    if not msg:
        msg = await telegram_bot.send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=False
        )
    
    if msg:
        BOT_STATE["tg_posts"] += 1
        
        # Pin if breaking news
        if is_breaking:
            try:
                await telegram_bot.pin_chat_message(
                    chat_id=config.TELEGRAM_CHANNEL_ID,
                    message_id=msg.message_id
                )
                logger.info("📌 Breaking News Pinned!")
            except Exception as e:
                logger.warning(f"Pin failed: {e}")
        
        return True
    
    return False

# =========================== WORKER ===========================

async def worker():
    """Main news processing loop"""
    global boost_until
    
    await db.init_db()
    logger.info("🚀 MEGA NEWS BOT 2026 STARTED")
    
    while True:
        try:
            BOT_STATE["last_run"] = datetime.now(config.ICT).strftime("%H:%M:%S")
            now = datetime.now(config.ICT)
            slot = config.get_current_slot()
            
            # Check trigger
            if trigger_event.is_set():
                logger.info("⚡ Manual Trigger Executing!")
                trigger_event.clear()
                max_posts = 10
                delay = 60
            # Check boost mode
            elif boost_until and now < boost_until:
                max_posts = 15
                delay = 60
                logger.info("🔥 BOOST MODE ACTIVE")
            else:
                max_posts = max(1, slot["max"] // 4)
                delay = slot["delay"]
                boost_until = None
            
            BOT_STATE["status"] = f"Processing ({slot['name']})"
            posted_count = 0
            
            categories = [
                ("cambodia", "🇰🇭"),
                ("international", "🌏"),
                ("thai", "🇹🇭"),
                ("vietnamese", "🇻🇳"),
                ("china", "🇨🇳"),
                ("tech", "💻"),
                ("crypto", "₿")
            ]
            
            for cat, emoji in categories:
                if posted_count >= max_posts:
                    break
                
                for src in config.NEWS_SOURCES.get(cat, []):
                    if posted_count >= max_posts:
                        break
                    
                    try:
                        feed = await fetch_rss(src["rss"])
                        if not feed or not feed.entries:
                            continue
                        
                        entry = feed.entries[0]
                        aid = await get_article_id(entry.title, entry.link)
                        
                        if await db.is_posted(aid):
                            continue
                        
                        # Build article
                        article = {
                            "title": entry.title,
                            "link": entry.link,
                            "summary": BeautifulSoup(
                                entry.get("summary", ""),
                                "html.parser"
                            ).get_text(strip=True)[:1000],
                            "image_url": get_image(entry, src["url"]),
                            "source": src["name"]
                        }
                        
                        # Check breaking news
                        is_breaking = False
                        if config.is_breaking_news(article) and not boost_until:
                            logger.info("🚨 BREAKING NEWS DETECTED -> BOOST ON")
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + emoji
                            is_breaking = True
                        
                        # Translate
                        article = await translate(article)
                        
                        # Post to both platforms
                        fb_ok = await post_to_facebook(article, emoji)
                        tg_ok = await post_to_telegram(article, emoji, is_breaking)
                        x_ok = await post_to_x(article, emoji)

                        if fb_ok or tg_ok or x_ok:
                            await db.mark_as_posted(aid, cat, src["name"])
                            posted_count += 1
                            BOT_STATE["total_posted"] += 1
                            
                            logger.info(
                                f"✅ Posted: {article['title_kh'][:40]}... "
                                f"[FB: {fb_ok}, TG: {tg_ok}, X: {x_ok}]"
                            )
                            
                            # Delay between posts
                            post_delay = 5 if boost_until else 15
                            await asyncio.sleep(post_delay)
                    
                    except Exception as e:
                        logger.error(f"❌ Error processing {src['name']}: {e}")
                        BOT_STATE["errors"] += 1
            
            # Calculate next run
            next_wait = delay
            next_time = (
                datetime.now(config.ICT) + timedelta(seconds=next_wait)
            ).strftime("%H:%M:%S")
            
            BOT_STATE["next_run"] = next_time
            BOT_STATE["status"] = "Sleeping"
            
            logger.info(
                f"✓ Cycle done. Posted: {posted_count}/{max_posts}. "
                f"Next: {next_time}"
            )
            
            # Wait with trigger support
            try:
                await asyncio.wait_for(trigger_event.wait(), timeout=next_wait)
                logger.info("⚡ Manual trigger received!")
                trigger_event.clear()
            except asyncio.TimeoutError:
                # Normal timeout
                pass
        
        except Exception as e:
            logger.error(f"❌ Worker loop error: {e}")
            BOT_STATE["errors"] += 1
            
            await send_error_report(
                "Worker Loop Error",
                traceback.format_exc()
            )
            
            await asyncio.sleep(60)

# =========================== WEB SERVER ===========================

HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Khmer News Bot 2026</title>
    <meta http-equiv="refresh" content="30">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0e27; color: #fff; padding: 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        h1 {{ text-align: center; color: #4CAF50; margin-bottom: 30px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin: 20px 0; }}
        .card {{ background: linear-gradient(135deg, #1e2a4a 0%, #2d3e5f 100%); padding: 25px; border-radius: 12px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }}
        .card h3 {{ margin: 0; font-size: 2.5em; color: #64B5F6; }}
        .card p {{ margin-top: 8px; color: #aaa; font-size: 0.9em; }}
        .btn {{ width: 100%; padding: 18px; background: linear-gradient(135deg, #E91E63, #9C27B0); color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 1.3em; font-weight: 600; transition: all 0.3s; }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(233,30,99,0.4); }}
        .status-card {{ background: #1a1f3a; padding: 20px; border-radius: 12px; margin: 20px 0; border-left: 4px solid #4CAF50; }}
        .status-card div {{ margin: 8px 0; font-size: 1.1em; }}
        .log-box {{ background: #000; padding: 15px; height: 350px; overflow-y: auto; font-family: 'Courier New', monospace; border: 1px solid #333; border-radius: 8px; }}
        .log-entry {{ border-bottom: 1px solid #222; padding: 4px 0; font-size: 0.85em; }}
        h3 {{ margin: 20px 0 10px; color: #64B5F6; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Khmer News Bot 2026</h1>
        <form action="/trigger" method="post">
            <button class="btn">⚡ Trigger Check Now</button>
        </form>
        <div class="status-card">
            <div><strong>Status:</strong> {status}</div>
            <div><strong>Last Run:</strong> {last_run}</div>
            <div><strong>Next Run:</strong> {next_run}</div>
        </div>
        <div class="grid">
            <div class="card"><h3>{total_posted}</h3><p>Total Posts</p></div>
            <div class="card"><h3>{fb_posts}</h3><p>Facebook</p></div>
            <div class="card"><h3>{tg_posts}</h3><p>Telegram</p></div>
            <div class="card"><h3>{translations}</h3><p>Translations</p></div>
            <div class="card"><h3>{cache_hits}</h3><p>Cache Hits</p></div>
            <div class="card"><h3 style="color:#f44336">{errors}</h3><p>Errors</p></div>
        </div>
        <h3>📜 Live Logs</h3>
        <div class="log-box">{logs}</div>
    </div>
</body>
</html>"""

async def dashboard(request):
    """Dashboard with stats"""
    logs_html = "".join([
        f"<div class='log-entry'>{log}</div>" 
        for log in BOT_STATE["logs"]
    ])
    
    return web.Response(
        text=HTML.format(
            status=BOT_STATE["status"],
            last_run=BOT_STATE["last_run"],
            next_run=BOT_STATE["next_run"],
            total_posted=BOT_STATE["total_posted"],
            fb_posts=BOT_STATE["fb_posts"],
            tg_posts=BOT_STATE["tg_posts"],
            translations=BOT_STATE["translations"],
            cache_hits=BOT_STATE["cache_hits"],
            errors=BOT_STATE["errors"],
            logs=logs_html
        ),
        content_type='text/html',
        charset='utf-8'
    )

async def trigger_check(request):
    """Manual trigger endpoint"""
    trigger_event.set()
    return web.Response(text="✅ Check Triggered!", content_type='text/html')

async def ping(request):
    """Lightweight ping for UptimeRobot"""
    return web.json_response({
        'status': 'alive',
        'timestamp': datetime.now(config.ICT).isoformat(),
        'uptime_posts': BOT_STATE['total_posted']
    })

async def health_check(request):
    """Detailed health check"""
    health_data = {
        'status': 'healthy' if BOT_STATE['status'] != 'Error' else 'unhealthy',
        'timestamp': datetime.now(config.ICT).isoformat(),
        'uptime_posts': BOT_STATE['total_posted'],
        'last_success': BOT_STATE['last_run'],
        'error_rate': round(BOT_STATE['errors'] / max(BOT_STATE['total_posted'], 1), 3),
        'components': {
            'telegram': 'ok' if telegram_bot else 'missing',
            'facebook': 'ok' if config.FB_PAGE_ID else 'missing',
            'gemini': 'ok' if config.GEMINI_API_KEY else 'missing'
        }
    }
    
    status_code = 200 if health_data['status'] == 'healthy' else 503
    return web.json_response(health_data, status=status_code)

async def metrics(request):
    """Metrics endpoint"""
    return web.json_response(BOT_STATE)

async def web_server():
    """Start web server"""
    app = web.Application()
    app.router.add_get("/", dashboard)
    app.router.add_post("/trigger", trigger_check)
    app.router.add_get("/ping", ping)
    app.router.add_get("/health", health_check)
    app.router.add_get("/metrics", metrics)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    
    logger.info(f"🌐 Web server started on port {config.PORT}")

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
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        err = traceback.format_exc()
        logger.critical(f"💥 FATAL CRASH:\n{err}")
        
        # Send error report
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            send_error_report("FATAL CRASH DETECTED", err)
        )
        loop.close()