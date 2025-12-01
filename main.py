import asyncio
import json
import logging
import time
import traceback
import html
import hashlib
import io
from datetime import datetime, timedelta
from urllib.parse import urljoin

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

class TranslationError(Exception):
    pass

# Configure Logger
logger_config.configure_logger()
logger = logger_config.get_logger(__name__)

# =========================== STATE & GLOBALS ===========================

BOT_STATE = {
    "status": "Starting...",
    "last_run": "Never",
    "next_run": "Calculating...",
    "logs": []
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
            self.usage[platform] = []

        async with self.locks[platform]:
            now = time.time()
            # Clean old
            while self.usage[platform] and now - self.usage[platform][0] > limit["period"]:
                self.usage[platform].pop(0)

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
        await db.mark_as_posted(aid, entry.title, src.get("category", "General"), src["name"])
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
            
            # Fetch sequentially to avoid rate limits
            for src in config.RSS_FEEDS:
                await fetch_rss_feed(src)
                await asyncio.sleep(1) # 1s delay between feeds
                
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

async def retry_failed_posts():
    """
    Background worker to process failed posts retry queue.
    Exponential backoff: 5, 15, 45, 135, 405 minutes.
    Max 5 retries before marking as DEAD.
    """
    logger.info("🔄 Retry queue processor started")
    
    while True:
        try:
            # Get pending retries from database
            pending = await db.get_pending_retries()
            
            if not pending:
                # No retries pending, wait before checking again
                await asyncio.sleep(300)  # Check every 5 minutes
                continue
            
            logger.debug(f"🔄 Processing {len(pending)} pending retries")
            
            for row in pending:
                try:
                    article = json.loads(row['article_data'])
                    platform = row['platform']
                    retry_count = row['retry_count']
                    article_id = article.get('article_id', 'Unknown')
                    
                    # Max 5 retries
                    if retry_count >= 5:
                        await db.update_retry_status(row['id'], 'DEAD')
                        logger.warning(f"💀 Giving up on {article_id} ({platform}) after 5 retries")
                        metrics.increment_error(f"{platform}_retry_dead")
                        continue
                    
                    logger.info(f"🔄 Retry attempt {retry_count + 1}/5 for {article_id} ({platform})")
                    
                    # Get translations from cache if possible
                    translations = {}
                    langs = ['km', 'th', 'vi', 'zh-CN']
                    for lang in langs:
                        cached = await db.get_translation(article_id, lang)
                        if cached:
                            translations[lang] = cached
                    
                    # If no Khmer translation in cache, skip retry
                    if not translations.get('km'):
                        logger.warning(f"⚠️ No cached translation for {article_id}, skipping retry")
                        await db.update_retry_status(row['id'], 'DEAD')
                        continue
                    
                    # Retry posting based on platform
                    success = False
                    if platform == "telegram":
                        success = await post_to_telegram(article, translations)
                    elif platform == "facebook":
                        success = await post_to_facebook(article, translations)
                    elif platform == "x":
                        success = await post_to_x(article, translations)
                    else:
                        logger.error(f"❌ Unknown platform: {platform}")
                        await db.update_retry_status(row['id'], 'DEAD')
                        continue
                    
                    if success:
                        # Success - mark as completed
                        await db.update_retry_status(row['id'], 'SUCCESS')
                        logger.info(f"✅ Retry succeeded: {article_id} ({platform})")
                        metrics.increment_error(f"{platform}_retry_success")
                        
                        # Mark as posted if it was telegram
                        if platform == "telegram":
                            await db.mark_as_posted(article_id, article.get('title', ''), article.get('category', 'General'), article.get('source', ''))
                    else:
                        # Failed - schedule next retry with exponential backoff
                        # Exponential backoff: 5, 15, 45, 135, 405 minutes
                        delay_minutes = 5 * (3 ** retry_count)
                        await db.update_retry_status(row['id'], 'PENDING', retry_count + 1, delay_minutes)
                        logger.warning(f"⚠️ Retry failed, will retry in {delay_minutes}m: {article_id} ({platform})")
                    
                    # Space out retries to avoid overwhelming APIs
                    await asyncio.sleep(10)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing retry {row.get('id')}: {e}", exc_info=True)
                    # Don't crash the entire worker on one bad retry
                    continue
            
        except Exception as e:
            logger.error(f"❌ Retry queue worker error: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait before retrying the worker itself
        
        # Wait before next cycle
        await asyncio.sleep(300)  # Check every 5 minutes


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
                if isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
                    translations[lang] = res[0]
                elif isinstance(res, dict):
                    translations[lang] = res
                else:
                    logger.error(f"Translation Error ({lang}): Invalid response type {type(res)}")
            
            # Critical Check for Khmer
            if not translations.get('km'):
                raise TranslationError("Critical: Khmer translation failed")
            
            # Post to all platforms using coordinator
            results = await post_to_all_platforms(article, translations)
            
            # Only mark as fully posted if Telegram succeeded
            if results.get("telegram"):
                await db.mark_pending_processed(row['id'])
                await db.mark_as_posted(article['article_id'], article['title'], article['category'], article['source'])
                logger.debug(f"✅ Marked as posted: {article['title'][:30]}...")
            else:
                # Telegram failed, move to retry queue
                await db.mark_pending_processed(row['id'])
                await db.add_failed_post(article['article_id'], "telegram", "SendFailed", json.dumps(article))
                logger.warning(f"⚠️ Telegram failed, added to retry: {article['title'][:30]}...")
            
            # Always wait between posts to prevent bursts
            await asyncio.sleep(config.POST_DELAY_NORMAL)
            
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
        
        caption = f"<b>{title}</b>\n\n{body}\n\n🔗 <a href='{article['link']}'>Read More</a>{config.SOCIAL_MEDIA_FOOTER}"
        
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

async def post_to_facebook(article: dict, translations: dict) -> bool:
    """
    Post article to Facebook using Graph API v19.0.
    Returns True on success, False on failure.
    """
    # Check credentials
    if not config.FB_PAGE_ID or not config.FB_ACCESS_TOKEN:
        logger.debug("⚠️ Facebook credentials missing, skipping")
        return False
    
    try:
        logger.debug(f"Posting to Facebook: {article['title'][:50]}...")
        
        # Acquire rate limit
        logger.debug("Waiting for Facebook rate limit...")
        await limiter.acquire("facebook")
        
        # Get Khmer translation (fallback to original)
        content = translations.get('km', {})
        title = content.get('title', article['title'])
        summary = content.get('body', article['summary'])
        
        # Format message with social media footer
        message = f"{title}\n\n{summary}\n\nអានបន្ត: {article['link']}{config.SOCIAL_MEDIA_FOOTER}"
        
        # Prepare API endpoint
        image_url = article.get('image_url')
        if image_url:
            # Use /photos endpoint
            url = f"https://graph.facebook.com/{config.FB_API_VERSION}/{config.FB_PAGE_ID}/photos"
            data = {
                "access_token": config.FB_ACCESS_TOKEN,
                "url": image_url,
                "caption": message
            }
        else:
            # Use /feed endpoint (text only)
            url = f"https://graph.facebook.com/{config.FB_API_VERSION}/{config.FB_PAGE_ID}/feed"
            data = {
                "access_token": config.FB_ACCESS_TOKEN,
                "message": message
            }
        
        # Make API call
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    post_id = result.get('id', 'Unknown')
                    logger.info(f"✅ Facebook posted: {post_id}")
                    
                    # Success metrics
                    metrics.increment_post("facebook", "success")
                    scheduler.record_post("facebook", article['category'])
                    return True
                else:
                    # Error handling
                    error_text = await resp.text()
                    logger.error(f"❌ Facebook post failed ({resp.status}): {error_text}")
                    
                    # Parse error details
                    try:
                        error_data = json.loads(error_text)
                        error_code = error_data.get('error', {}).get('code')
                        error_msg = error_data.get('error', {}).get('message', error_text)
                    except:
                        error_code = None
                        error_msg = error_text
                    
                    # Specific error handling
                    if resp.status == 400:
                        # Invalid token or malformed request - don't retry
                        logger.critical(f"🚨 Facebook invalid request: {error_msg}")
                        metrics.increment_error("facebook_auth_error")
                        await db.add_failed_post(article['article_id'], "facebook", "BadRequest", json.dumps(article))
                        
                    elif resp.status == 401:
                        # Unauthorized - invalid credentials
                        logger.critical(f"🚨 Facebook unauthorized: {error_msg}")
                        metrics.increment_error("facebook_auth_error")
                        
                    elif resp.status == 403:
                        # Permission denied
                        logger.error(f"❌ Facebook permission denied: {error_msg}")
                        metrics.increment_error("facebook_permission_error")
                        
                    elif error_code == 190:
                        # Token expired
                        logger.critical(f"🚨 Facebook token expired: {error_msg}")
                        metrics.increment_error("facebook_token_expired")
                        
                    elif resp.status in [429, 613] or error_code in [4, 17, 32, 613]:
                        # Rate limit hit (HTTP 429 or error codes 4, 17, 32, 613)
                        logger.warning(f"⚠️ Facebook rate limit hit: {error_msg}")
                        metrics.track_rate_limit("facebook")
                        await db.add_failed_post(article['article_id'], "facebook", "RateLimit", json.dumps(article))
                        
                    else:
                        # Other errors - retry with exponential backoff
                        logger.error(f"❌ Facebook error {resp.status}: {error_msg}")
                        await db.add_failed_post(article['article_id'], "facebook", f"HTTP_{resp.status}", json.dumps(article))
                    
                    metrics.increment_post("facebook", "failed")
                    return False
                    
    except asyncio.TimeoutError:
        logger.error(f"❌ Facebook timeout for: {article['title'][:50]}")
        metrics.increment_error("facebook_timeout")
        await db.add_failed_post(article['article_id'], "facebook", "Timeout", json.dumps(article))
        return False
        
    except aiohttp.ClientError as e:
        logger.error(f"❌ Facebook network error: {e}")
        metrics.increment_error("facebook_network_error")
        await db.add_failed_post(article['article_id'], "facebook", "NetworkError", json.dumps(article))
        return False
        
    except Exception as e:
        logger.error(f"❌ Facebook unexpected error: {e}", exc_info=True)
        metrics.increment_error("facebook_error")
        await db.add_failed_post(article['article_id'], "facebook", str(type(e).__name__), json.dumps(article))
        return False

async def post_to_x(article: dict, translations: dict) -> bool:
    """
    Post article to X (Twitter) using tweepy.
    Returns True on success, False on failure.
    Handles image upload and 280 character limit.
    """
    # Check if Twitter client is available
    if not twitter_client:
        logger.debug("⚠️ X credentials missing, skipping")
        return False
    
    try:
        logger.debug(f"Posting to X: {article['title'][:50]}...")
        
        # Acquire rate limit
        logger.debug("Waiting for X rate limit...")
        await limiter.acquire("x")
        
        # Get translation (prefer Khmer, fallback to English, then original)
        content = translations.get('km', translations.get('en', {}))
        title = content.get('title', article['title'])
        
        # Format tweet with character limit
        # Twitter shortens links to 23 chars (t.co)
        link = article['link']
        category = article.get('category', 'News').replace('_', ' ').title()
        hashtags = f"\n\n#{category.replace(' ', '')} #Cambodia #News"
        
        # Add social media footer (compact version for Twitter due to char limit)
        footer = "\n\n📢 Follow: t.me/AIDailyNewsKH"
        
        # Calculate available space
        # 280 total - 23 (link) - len(hashtags) - len(footer) - 2 (newlines before link)
        reserved = 23 + len(hashtags) + len(footer) + 2
        available = 280 - reserved
        
        # Truncate title if needed
        if len(title) > available:
            title = title[:available-3] + "..."
        
        # Compose tweet
        tweet_text = f"{title}\n\n{link}{hashtags}{footer}"
        
        # Handle image upload if present
        media_ids = None
        image_url = article.get('image_url')
        if image_url:
            try:
                logger.debug(f"Downloading image from: {image_url}")
                
                # Download image
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(image_url) as resp:
                        if resp.status == 200:
                            image_data = await resp.read()
                            
                            # Check size (max 5MB)
                            if len(image_data) > config.IMAGE_MAX_SIZE_MB * 1024 * 1024:
                                logger.warning(f"⚠️ Image too large ({len(image_data)/1024/1024:.1f}MB), skipping")
                            else:
                                # Upload to Twitter using API v1.1 (v2 doesn't support media yet)
                                auth = tweepy.OAuth1UserHandler(
                                    config.X_API_KEY,
                                    config.X_API_SECRET,
                                    config.X_ACCESS_TOKEN,
                                    config.X_ACCESS_TOKEN_SECRET
                                )
                                api = tweepy.API(auth)
                                
                                # Upload media in thread pool (blocking operation)
                                loop = asyncio.get_running_loop()
                                media = await loop.run_in_executor(
                                    None, 
                                    lambda: api.media_upload(filename="image.jpg", file=io.BytesIO(image_data))
                                )
                                media_ids = [media.media_id]
                                logger.debug(f"✅ Image uploaded: {media.media_id}")
                        else:
                            logger.warning(f"⚠️ Image download failed ({resp.status}), posting text-only")
                            
            except asyncio.TimeoutError:
                logger.warning("⚠️ Image download timeout, posting text-only")
            except Exception as e:
                logger.warning(f"⚠️ Image upload error: {e}, posting text-only")
        
        # Post tweet
        loop = asyncio.get_running_loop()
        
        # Create tweet in thread pool (tweepy is synchronous)
        response = await loop.run_in_executor(
            None,
            lambda: twitter_client.create_tweet(
                text=tweet_text,
                media_ids=media_ids
            )
        )
        
        # Success
        tweet_id = response.data['id']
        logger.info(f"✅ X posted: {tweet_id}")
        
        # Success metrics
        metrics.increment_post("x", "success")
        scheduler.record_post("x", article['category'])
        return True
        
    except tweepy.errors.TooManyRequests as e:
        # Rate limit hit
        logger.warning(f"⚠️ X rate limit hit: {e}")
        metrics.track_rate_limit("x")
        await db.add_failed_post(article['article_id'], "x", "RateLimit", json.dumps(article))
        metrics.increment_post("x", "failed")
        return False
        
    except tweepy.errors.Forbidden as e:
        # 403: Duplicate tweet or policy violation
        logger.warning(f"⚠️ X forbidden (duplicate or policy): {e}")
        # Mark as posted (don't retry duplicates)
        metrics.increment_post("x", "success")  # Count as success to avoid retry
        return True  # Return True to prevent retry
        
    except tweepy.errors.Unauthorized as e:
        # 401: Invalid credentials
        logger.critical(f"🚨 X unauthorized (invalid credentials): {e}")
        metrics.increment_error("x_auth_error")
        metrics.increment_post("x", "failed")
        return False
        
    except tweepy.errors.BadRequest as e:
        # 400: Malformed request
        logger.error(f"❌ X bad request: {e}")
        metrics.increment_error("x_bad_request")
        await db.add_failed_post(article['article_id'], "x", "BadRequest", json.dumps(article))
        metrics.increment_post("x", "failed")
        return False
        
    except (tweepy.errors.TwitterServerError, aiohttp.ClientError) as e:
        # Connection/server errors - retry
        logger.error(f"❌ X connection error: {e}")
        metrics.increment_error("x_network_error")
        await db.add_failed_post(article['article_id'], "x", "NetworkError", json.dumps(article))
        metrics.increment_post("x", "failed")
        return False
        
    except asyncio.TimeoutError:
        logger.error(f"❌ X timeout for: {article['title'][:50]}")
        metrics.increment_error("x_timeout")
        await db.add_failed_post(article['article_id'], "x", "Timeout", json.dumps(article))
        metrics.increment_post("x", "failed")
        return False
        
    except Exception as e:
        logger.error(f"❌ X unexpected error: {e}", exc_info=True)
        metrics.increment_error("x_error")
        await db.add_failed_post(article['article_id'], "x", str(type(e).__name__), json.dumps(article))
        metrics.increment_post("x", "failed")
        return False

async def post_to_all_platforms(article: dict, translations: dict) -> dict:
    """
    Unified posting coordinator for all platforms.
    Returns dict with results for each platform.
    
    Flow:
    1. Post to Telegram first (blocking)
    2. Only continue if Telegram succeeds
    3. Post to Facebook and X in parallel
    """
    results = {
        "telegram": False,
        "facebook": False,
        "x": False
    }
    
    try:
        # Step 1: Post to Telegram (critical - must succeed)
        logger.debug(f"📤 Posting to platforms: {article['title'][:40]}...")
        results["telegram"] = await post_to_telegram(article, translations)
        
        # Step 2: Only post to other platforms if Telegram succeeded
        if not results["telegram"]:
            logger.warning(f"⚠️ Telegram failed, skipping other platforms for: {article['title'][:40]}")
            return results
        
        # Step 3: Post to Facebook and X in parallel (non-blocking)
        fb_task = post_to_facebook(article, translations)
        x_task = post_to_x(article, translations)
        
        # Gather results without raising exceptions
        platform_results = await asyncio.gather(fb_task, x_task, return_exceptions=True)
        
        # Process results
        if isinstance(platform_results[0], bool):
            results["facebook"] = platform_results[0]
        elif isinstance(platform_results[0], Exception):
            logger.error(f"❌ Facebook task error: {platform_results[0]}")
            results["facebook"] = False
            
        if isinstance(platform_results[1], bool):
            results["x"] = platform_results[1]
        elif isinstance(platform_results[1], Exception):
            logger.error(f"❌ X task error: {platform_results[1]}")
            results["x"] = False
        
        # Log summary
        status_emojis = {
            "telegram": "✅" if results["telegram"] else "❌",
            "facebook": "✅" if results["facebook"] else "❌",
            "x": "✅" if results["x"] else "❌"
        }
        logger.info(f"📊 Posted '{article['title'][:30]}...' to: Telegram {status_emojis['telegram']}, Facebook {status_emojis['facebook']}, X {status_emojis['x']}")
        
    except Exception as e:
        logger.error(f"❌ post_to_all_platforms error: {e}", exc_info=True)
    
    return results

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
        retry_failed_posts(),  # New retry queue processor
        broadcast_metrics(),
        db.cleanup_old_records()  # Run once on start, then internally scheduled
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass