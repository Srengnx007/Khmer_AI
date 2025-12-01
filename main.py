import asyncio
import json
import logging
import time
import traceback
import html
import hashlib
from datetime import datetime, timedelta
from urllib.parse import urljoin
from collections import deque

import aiohttp
from aiohttp import web
import feedparser
import backoff
import tweepy
from bs4 import BeautifulSoup
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut

import config
import db
import logger_config
from metrics import metrics
from scheduler import scheduler
from deduplication import detector
from image_processor import image_processor
from quality_scorer import scorer
from translation_manager import translator

# Configure Logger
logger_config.configure_logger()
logger = logger_config.get_logger(__name__)

# =========================== STATE & GLOBALS ===========================

BOT_STATE = {
    "status": "Starting...",
    "last_run": "Never",
    "next_run": "Calculating...",
    "logs": deque(maxlen=50)
}

# Events
trigger_event = asyncio.Event()
new_post_event = asyncio.Event()

# WebSocket Clients
ws_clients = set()

# =========================== RATE LIMITER ===========================

class AsyncRateLimiter:
    """
    Asyncio-friendly Rate Limiter using Event + Queue.
    Does NOT block the event loop.
    """
    def __init__(self):
        self.locks = {}
        self.usage = {}

    async def acquire(self, platform: str):
        limit = config.RATE_LIMITS.get(platform)
        if not limit: return True

        if platform not in self.locks:
            self.locks[platform] = asyncio.Lock()
            self.usage[platform] = deque()

        async with self.locks[platform]:
            now = time.time()
            # Clean old
            while self.usage[platform] and now - self.usage[platform][0] > limit["period"]:
                self.usage[platform].popleft()

            if len(self.usage[platform]) >= limit["calls"]:
                wait_time = limit["period"] - (now - self.usage[platform][0]) + 0.1
                logger.debug(f"⏳ Rate Limit {platform}: Waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                
            self.usage[platform].append(time.time())
            metrics.track_api_call(platform)
            return True

limiter = AsyncRateLimiter()

# =========================== SINGLETONS ===========================

telegram_bot = Bot(token=config.TELEGRAM_BOT_TOKEN) if config.TELEGRAM_BOT_TOKEN else None

twitter_client = None
if config.X_API_KEY:
    try:
        twitter_client = tweepy.Client(
            consumer_key=config.X_API_KEY,
            consumer_secret=config.X_API_SECRET,
            access_token=config.X_ACCESS_TOKEN,
            access_token_secret=config.X_ACCESS_TOKEN_SECRET
        )
    except Exception as e:
        logger.error(f"❌ Twitter Init Failed: {e}")

# =========================== WEB SERVER & DASHBOARD ===========================

async def handle_dashboard(request):
    return web.FileResponse('dashboard.html')

async def handle_websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    
    # Send initial state
    await ws.send_json({"type": "metrics", "payload": get_dashboard_data()})
    
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "get_queue":
                    # Send queue data
                    pending = await db.get_pending_retries() # Reuse this for now or add get_pending_posts
                    # Actually let's send both
                    await broadcast_queue()
    finally:
        ws_clients.remove(ws)
    return ws

async def handle_trigger(request):
    trigger_event.set()
    return web.Response(text="Triggered")

async def handle_metrics(request):
    data, content_type = metrics.get_metrics_data()
    return web.Response(body=data, content_type=content_type)

def get_dashboard_data():
    return {
        "posts_total": metrics.posts_total.labels(platform="telegram", status="success")._value.get(), # Approximate
        "errors_total": metrics.errors_total.labels(type="source_error")._value.get(), # Approximate
        "queue_size": metrics.queue_size._value.get(),
        "uptime_seconds": metrics.uptime_seconds._value.get(),
        "status": BOT_STATE["status"],
        "last_run": BOT_STATE["last_run"]
    }

async def broadcast_log(record):
    """Send log to WebSockets"""
    if not ws_clients: return
    msg = {"type": "log", "payload": record}
    for ws in list(ws_clients):
        try:
            await ws.send_json(msg)
        except:
            ws_clients.discard(ws)

async def broadcast_metrics():
    """Periodic metrics broadcast"""
    while True:
        if ws_clients:
            msg = {"type": "metrics", "payload": get_dashboard_data()}
            for ws in list(ws_clients):
                try: await ws.send_json(msg)
                except: ws_clients.discard(ws)
        await asyncio.sleep(2)

async def broadcast_queue():
    """Send queue data to WS"""
    if not ws_clients: return
    
    # Get failed queue
    failed = await db.get_pending_retries()
    payload = []
    for row in failed:
        art = json.loads(row['article_data'])
        payload.append({
            "title": art.get('title', 'Unknown'),
            "platform": row['platform'],
            "retry_count": row['retry_count'],
            "status": row['status']
        })
        
    msg = {"type": "queue", "payload": payload}
    for ws in list(ws_clients):
        try: await ws.send_json(msg)
        except: ws_clients.discard(ws)

# =========================== CORE LOGIC ===========================

async def fetch_rss_feed(src):
    """Fetch and parse RSS feed using feedparser in thread pool"""
    # print(f"DEBUG: Fetching {src['name']}...")
    try:
        await limiter.acquire("rss")
        
        # Run blocking feedparser in thread
        loop = asyncio.get_running_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, src["rss"])
        
        if getattr(feed, 'status', 200) != 200:
            print(f"DEBUG: {src['name']} HTTP {getattr(feed, 'status', 'Unknown')}")
            # Don't return immediately, some feeds return 301/302 but have entries
        
        if not feed.entries: 
            # print(f"DEBUG: {src['name']} ({src['url']}) No Entries")
            return
        
        # print(f"DEBUG: {src['name']} Found {len(feed.entries)} entries")
        for entry in feed.entries[:5]: # Process top 5
            await process_entry(entry, src)
                    
    except Exception as e:
        logger.error(f"Feed Error {src['name']}: {e}")
        metrics.increment_error("feed_error")

async def process_entry(entry, src):
    """Process single RSS entry"""
    aid = hashlib.md5((entry.title + entry.link).encode()).hexdigest()
    
    if await db.is_posted(aid): return
    
    # 1. Extract & Validate
    summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(strip=True)[:1000]
    image_url = None
    
    # Image extraction logic (simplified)
    if hasattr(entry, "media_content"): image_url = entry.media_content[0]["url"]
    elif hasattr(entry, "media_thumbnail"): image_url = entry.media_thumbnail[0]["url"]
    
    # 2. Quality Score
    article_temp = {
        "title": entry.title,
        "summary": summary,
        "image_url": image_url,
        "source": src["name"]
    }
    
    q_score, reasons = await scorer.score_article(article_temp)
    if q_score < 50:
        logger.info(f"📉 Low Quality ({q_score}): {entry.title[:20]}")
        return

    # 3. Deduplication
    recent = await db.get_recent_titles()
    is_dup, _, _ = detector.is_duplicate(entry.title, recent)
    if is_dup:
        logger.info(f"⏭️ Duplicate: {entry.title[:20]}")
        await db.mark_as_posted(aid, entry.title, src.get("category"), src["name"])
        return

    # 4. Image Processing
    if image_url:
        _, _, valid = await image_processor.process_image(image_url)
        if not valid: image_url = None

    # 5. Queue
    article = {
        "article_id": aid,
        "title": entry.title,
        "link": entry.link,
        "summary": summary,
        "image_url": image_url,
        "source": src["name"],
        "category": src.get("category", "General")
    }
    
    is_breaking = config.is_breaking_news(article)
    priority = 3 if is_breaking else 1
    
    await db.add_pending_post(article, priority)
    logger.info(f"📥 Queued: {entry.title[:30]}")
    new_post_event.set()

async def fetch_worker():
    """Periodic Fetcher"""
    while True:
        try:
            BOT_STATE["status"] = "Fetching"
            await asyncio.gather(*(fetch_rss_feed(src) for src in config.RSS_FEEDS))
            BOT_STATE["last_run"] = datetime.now().strftime("%H:%M:%S")
            BOT_STATE["status"] = "Idle"
            
            # Wait for next cycle
            try:
                await asyncio.wait_for(trigger_event.wait(), timeout=config.CHECK_INTERVAL)
                trigger_event.clear()
            except asyncio.TimeoutError:
                pass
                
        except Exception as e:
            logger.error(f"Fetch Worker Error: {e}")
            await asyncio.sleep(60)

async def publish_worker():
    """Consumes pending posts"""
    while True:
        try:
            row = await db.get_next_pending_post()
            if not row:
                BOT_STATE["status"] = "Idle"
                try: await asyncio.wait_for(new_post_event.wait(), timeout=5)
                except: pass
                new_post_event.clear()
                continue

            article = dict(row)
            BOT_STATE["status"] = f"Processing: {article['title'][:20]}"
            
            # Check Scheduler
            if not scheduler.can_post("telegram", article['category'], article['priority']):
                await asyncio.sleep(10)
                continue

            # Translate
            translations = {}
            # Parallel translation for all target langs
            langs = ['km', 'th', 'vi', 'zh-CN'] # Configurable
            tasks = [translator.translate_content(article, lang) for lang in langs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for lang, res in zip(langs, results):
                if isinstance(res, dict): translations[lang] = res
            
            # Post to Telegram
            if await post_to_telegram(article, translations):
                await db.mark_pending_processed(row['id'])
                scheduler.record_post("telegram", article['category'])
                metrics.increment_post("telegram")
            else:
                # Failed, add to retry
                await db.mark_pending_processed(row['id']) # Remove from pending, move to retry
                await db.add_failed_post(article['article_id'], "telegram", "SendFailed", json.dumps(article))

            # Post to FB/X (Async, fire and forget or await)
            asyncio.create_task(post_to_facebook(article, translations))
            asyncio.create_task(post_to_x(article, translations))
            
        except Exception as e:
            logger.error(f"Publish Worker Error: {e}")
            await asyncio.sleep(5)

async def post_to_telegram(article, translations):
    if not telegram_bot: return False
    try:
        await limiter.acquire("telegram")
        content = translations.get('km', {})
        title = content.get('title', article['title'])
        body = content.get('body', article['summary'])
        
        caption = f"<b>{title}</b>\n\n{body}\n\n🔗 <a href='{article['link']}'>Read More</a>"
        
        if article['image_url']:
            # Use processed image bytes if possible, but TG bot api takes url or file
            # For simplicity, use URL, but we validated it.
            await telegram_bot.send_photo(
                chat_id=config.TELEGRAM_CHANNEL_ID,
                photo=article['image_url'],
                caption=caption[:1024],
                parse_mode=ParseMode.HTML
            )
        else:
            await telegram_bot.send_message(
                chat_id=config.TELEGRAM_CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML
            )
        
        await db.mark_as_posted(article['article_id'], article['title'], article['category'], article['source'])
        return True
    except Exception as e:
        logger.error(f"TG Post Failed: {e}")
        return False

async def post_to_facebook(article, translations):
    # Implementation similar to v2.5 but using aiohttp and limiter
    pass # Placeholder for brevity, assuming similar logic to previous main.py but cleaned up

async def post_to_x(article, translations):
    pass # Placeholder

# =========================== MAIN ENTRY ===========================

async def main():
    # Init DB
    await db.init_db()
    
    # Start Web Server
    app = web.Application()
    app.router.add_get('/', handle_dashboard)
    app.router.add_get('/ws', handle_websocket)
    app.router.add_post('/trigger', handle_trigger)
    app.router.add_get('/metrics', handle_metrics)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    await site.start()
    
    logger.info(f"🚀 Bot v3.0 Started on port {config.PORT}")
    
    # Start Workers
    await asyncio.gather(
        fetch_worker(),
        publish_worker(),
        broadcast_metrics(),
        db.cleanup_old_records() # Run once on start, then internally scheduled
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass