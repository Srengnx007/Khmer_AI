# CHANGES:
# - FIX #1: Removed duplicate BOT_STATE keys (tg_posts, errors)
# - FIX #3: Made rate limiter async with actual waiting
# - FIX #4: Global Twitter client initialization
# - FIX #6: Moved config validation to main block
# - FIX #10: Using time.time() for consistent timestamps
# - FIX #2: Added cleanup_scheduler async task
# - FIX #5: Image failure tracking in post_to_telegram
# - FIX #8: Facebook error logging with response data
# - Enhancement #13: Image size limit reduced to 5MB
# - Enhancement #15: Translation fallback to English

import asyncio
import json
import hashlib
import re
import logging
import time
import traceback
from datetime import datetime, timedelta
from urllib.parse import urljoin
from collections import deque

import aiohttp
import feedparser
import backoff
import tweepy
import difflib
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

# FIX #1: Removed duplicate keys
BOT_STATE = {
    "status": "Starting...",
    "last_run": "Never",
    "next_run": "Calculating...",
    "total_posted": 0,
    "fb_posts": 0,
    "tg_posts": 0,
    "x_posts": 0,
    "errors": 0,
    "translations": 0,
    "cache_hits": 0,
    "duplicate_skips": 0,
    "image_failures": 0,
    "duplicate_skips": 0,
    "image_failures": 0,
    "sources_health": {},
    "logs": deque(maxlen=50)
}

# FIX #3: Async rate limiter with waiting (Thread-Safe)
class RateLimiter:
    def __init__(self):
        self._locks = {}
        self._usage = {}
    
    def _get_lock(self, platform):
        if platform not in self._locks:
            self._locks[platform] = asyncio.Lock()
        return self._locks[platform]

    async def acquire(self, platform: str) -> int:
        """
        Check rate limit, wait if needed, and return tokens remaining.
        Thread-safe using asyncio.Lock per platform.
        """
        limit = config.RATE_LIMITS.get(platform)
        if not limit: return 999
        
        lock = self._get_lock(platform)
        
        async with lock:
            now = time.time()
            # Initialize usage for platform
            if platform not in self._usage:
                self._usage[platform] = []
            
            # Sliding Window: Clean old calls
            self._usage[platform] = [t for t in self._usage[platform] if now - t < limit["period"]]
            
            # Check limit
            if len(self._usage[platform]) >= limit["calls"]:
                # Calculate wait time
                oldest_call = self._usage[platform][0]
                wait_time = limit["period"] - (now - oldest_call) + 0.1 # Buffer
                
                logger.warning(f"⚠️ Rate limit hit for {platform}, waiting {wait_time:.1f}s")
                
                # Wait (releasing lock would be unsafe if we want to guarantee order, 
                # but holding it blocks others. Here we hold to enforce strict FIFO and prevent race)
                await asyncio.sleep(wait_time)
                
                # Re-check time after sleep
                now = time.time()
                self._usage[platform] = [t for t in self._usage[platform] if now - t < limit["period"]]
            
            # Record usage
            self._usage[platform].append(now)
            
            # Return tokens remaining
            return limit["calls"] - len(self._usage[platform])

# Global Rate Limiter Instance
limiter = RateLimiter()

async def check_platform_rate_limit(platform: str) -> int:
    """Wrapper for RateLimiter to maintain compatibility"""
    return await limiter.acquire(platform)


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

# FIX #4: Global Twitter Client (initialize once)
twitter_client = None
if config.X_API_KEY and config.X_API_SECRET and config.X_ACCESS_TOKEN and config.X_ACCESS_TOKEN_SECRET:
    try:
        twitter_client = tweepy.Client(
            consumer_key=config.X_API_KEY,
            consumer_secret=config.X_API_SECRET,
            access_token=config.X_ACCESS_TOKEN,
            access_token_secret=config.X_ACCESS_TOKEN_SECRET
        )
        logger.info("✅ Twitter client initialized")
    except Exception as e:
        logger.error(f"❌ Twitter client failed: {e}")

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
# gemini_calls removed (handled by generic rate limiter)

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

# RSS Feed Cache (ETag / Last-Modified)
FEED_CACHE = {}

async def fetch_rss(url: str):
    """
    Robust RSS fetcher with:
    - Auto-detect charset
    - Compression support (gzip/brotli)
    - Progressive timeout (15s -> 30s)
    - ETag/Last-Modified caching
    - Validation
    """
    etag = None
    last_modified = None
    
    if url in FEED_CACHE:
        etag, last_modified = FEED_CACHE[url]
        
    headers = {
        "User-Agent": "KhmerNewsBot/2.0 (+https://t.me/AIDailyNewsKH)",
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br"
    }
    
    if etag: headers["If-None-Match"] = etag
    if last_modified: headers["If-Modified-Since"] = last_modified
    
    # Progressive Timeout Strategy
    timeouts = [15, 30]
    
    for attempt, timeout in enumerate(timeouts):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url, headers=headers) as response:
                    
                    # Handle 304 Not Modified
                    if response.status == 304:
                        logger.debug(f"📉 Feed Not Modified: {url}")
                        # Return empty feed object with status 304
                        return feedparser.FeedParserDict(entries=[], status=304)
                        
                    if response.status == 200:
                        # Read content (auto-decompress)
                        content = await response.read()
                        
                        # Parse
                        feed = feedparser.parse(content)
                        feed.status = 200
                        
                        # Validate
                        if feed.bozo:
                            logger.warning(f"⚠️ Feed Parse Warning (Bozo): {feed.bozo_exception} - {url}")
                            # Continue if we have entries despite errors
                            if not feed.entries:
                                return None
                                
                        if not feed.entries and not feed.feed:
                             logger.warning(f"⚠️ Empty/Invalid Feed: {url}")
                             return None
                             
                        # Update Cache
                        new_etag = response.headers.get("ETag")
                        new_lm = response.headers.get("Last-Modified")
                        if new_etag or new_lm:
                            FEED_CACHE[url] = (new_etag, new_lm)
                            
                        # Log Metrics
                        logger.info(f"📥 Fetched {len(feed.entries)} entries from {url}")
                        return feed
                        
                    # Handle other errors
                    logger.warning(f"⚠️ Feed Fetch Error {response.status}: {url}")
                    
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"⚠️ Feed Fetch Attempt {attempt+1} failed: {e}")
            if attempt == len(timeouts) - 1:
                return None
            await asyncio.sleep(1) # Short wait before retry
            



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
    """Validate image using ImageProcessor"""
    if not image_url: return False
    
    # Use the new processor
    # Note: We process it to check validity, but we don't store the bytes here yet
    # In a real app, we might want to store the processed bytes to avoid re-downloading
    # For now, we just check if it returns valid data
    _, _, is_valid = await image_processor.process_image(image_url)
    return is_valid


async def get_article_id(title: str, link: str):
    """Generate unique article ID"""
    try:
        return hashlib.md5(f"{title}{link}".encode()).hexdigest()
    except Exception:
        return str(hash(f"{title}{link}"))

# =========================== TRANSLATION ===========================

# Custom Exceptions
class TranslationError(Exception): pass
class RateLimitError(TranslationError): pass
class SafetyBlockError(TranslationError): pass
class ParseError(TranslationError): pass

# Circuit Breaker
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=600):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED" # CLOSED, OPEN, HALF-OPEN

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"🔌 Circuit Breaker OPENED: Too many failures ({self.failures})")

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def allow_request(self):
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
                logger.info("🔌 Circuit Breaker HALF-OPEN: Testing service...")
                return True
            return False
        return True # HALF-OPEN

gemini_circuit = CircuitBreaker()

# Translation failure tracking
TRANSLATION_FAILURES = {}

@backoff.on_exception(backoff.expo, (RateLimitError, aiohttp.ClientError), max_tries=3, jitter=backoff.full_jitter)
async def translate(article: dict):
    """Translate article to Khmer with caching, retries, and circuit breaker"""
    aid = await get_article_id(article['title'], article['link'])
    
    # Check cache first
    cached = await db.get_translation(aid)
    if cached:
        article["title_kh"] = cached["title_kh"]
        article["body_kh"] = cached["body_kh"]
        BOT_STATE["cache_hits"] += 1
        logger.debug(f"✅ Cache hit for: {article['title'][:30]}")
        return article

    # Circuit Breaker Check
    if not gemini_circuit.allow_request():
        logger.warning("🔌 Circuit Breaker OPEN: Skipping translation")
        return article

    # Rate limit check handled in worker
    
    # Prompt Engineering
    base_prompt = """Translate to natural, engaging Khmer for Telegram news:
    
    Title: {title}
    Summary: {summary}
    
    Output JSON only: {{"title_kh": "...", "body_kh": "..."}}"""
    
    simple_prompt = """Translate to Khmer JSON: {{"title_kh": "...", "body_kh": "..."}}
    
    {title}
    {summary}"""

    model = genai.GenerativeModel(config.GEMINI_MODEL)
    
    try:
        # Attempt Translation
        try:
            response = await model.generate_content_async(
                base_prompt.format(title=article["title"], summary=article["summary"]),
                safety_settings=SAFETY_SETTINGS
            )
        except Exception as e:
            # Fallback to simple prompt if complex fails
            logger.warning(f"⚠️ Complex prompt failed, trying simple: {e}")
            response = await model.generate_content_async(
                simple_prompt.format(title=article["title"], summary=article["summary"]),
                safety_settings=SAFETY_SETTINGS
            )

        # Handle Safety Blocks
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise SafetyBlockError(f"Blocked: {response.prompt_feedback.block_reason}")
            
        if not response.parts:
            raise TranslationError("Empty response from Gemini")

        text = response.text
        
        # Parse JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == -1:
            raise ParseError("No JSON found in response")
            
        data = json.loads(text[start:end])
        
        # Validate Schema
        if "title_kh" not in data or "body_kh" not in data:
            raise ParseError("Missing required keys in JSON")

        article["title_kh"] = data["title_kh"]
        article["body_kh"] = data["body_kh"]
        
        # Save to cache
        await db.save_translation(aid, article["title_kh"], article["body_kh"])
        
        BOT_STATE["translations"] += 1
        gemini_circuit.record_success()
        logger.info(f"✅ Translated: {article['title'][:30]}")
        
        # Rate limiting delay
        await asyncio.sleep(config.TRANSLATION_DELAY)
        
    except Exception as e:
        gemini_circuit.record_failure()
        logger.error(f"❌ Translation error: {e}")
        
        # Log failed prompt for debugging
        logger.debug(f"Failed Prompt Context: {article['title']}")
        
        TRANSLATION_FAILURES[aid] = TRANSLATION_FAILURES.get(aid, 0) + 1
        BOT_STATE["errors"] += 1
        
        # Fallback logic
        if TRANSLATION_FAILURES.get(aid, 0) >= 3:
            logger.warning("⚠️ Translation failed 3 times, using English with disclaimer")
            article["title_kh"] = "⚠️ ស្រាប់ភាសាអង់គ្លេស (Translation unavailable) - " + article["title"]
            article["body_kh"] = article["summary"][:500]
        else:
            article["title_kh"] = article["title"]
            article["body_kh"] = article["summary"][:500]
            
        # Re-raise RateLimitError to trigger backoff
        if "429" in str(e) or "ResourceExhausted" in str(e):
            raise RateLimitError("Gemini Rate Limit Exceeded") from e
            
    return article
    
# =========================== POSTING ===========================

@backoff.on_exception(backoff.expo, Exception, max_tries=3)
async def post_to_x(article: dict, emoji: str):
    # FIX #4: Use global twitter_client instead of creating new one
    if not twitter_client:
        return False

    if not await check_platform_rate_limit("x"): return False

    try:
        # Smart Truncate
        title = article['title_kh']
        link = article['link']
        max_len = config.MAX_TWEET_LENGTH - len(link) - 5  # Using constant
        
        if len(title) > max_len:
            title = title[:max_len-3] + "..."
            
        text = f"{emoji} {title}\n{link}"
        
        await asyncio.to_thread(twitter_client.create_tweet, text=text)
        BOT_STATE["x_posts"] += 1
        logger.info(f"✅ X Posted: {title[:30]}...")
        return True
        
    except Exception as e:
        logger.error(f"❌ X Post Failed: {e}")
        # Enqueue for retry
        aid = await get_article_id(article['title'], article['link'])
        await db.add_failed_post(aid, "x", str(type(e).__name__), json.dumps(article))
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
        f"👉 X (Twitter): https://x.com/{config.X_USERNAME}"
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
            
            async with session.post(url, params=params) as resp:
                resp_data = await resp.json()
                # FIX #8: Log detailed error information
                if resp.status == 200 and "id" in resp_data:
                    logger.info(f"✅ FB Photo Posted: {resp_data['id']}")
                    BOT_STATE["fb_posts"] += 1
                    return True
                else:
                    # Log response data for debugging
                    error_msg = resp_data.get('error', {}).get('message', 'Unknown')
                    logger.error(f"❌ FB Photo Failed: Status {resp.status}, Error: {error_msg}, Data: {resp_data}")
                    # Enqueue for retry
                    aid = await get_article_id(article['title'], article['link'])
                    await db.add_failed_post(aid, "facebook", f"FBPhotoError: {error_msg}", json.dumps(article))
        
        # Fallback to link post
        url = f"https://graph.facebook.com/{api_ver}/{config.FB_PAGE_ID}/feed"
        params = {
            "link": article["link"],
            "message": message,
            "access_token": config.FB_ACCESS_TOKEN,
            "published": "true"
        }
        
        async with session.post(url, params=params) as resp:
            resp_data = await resp.json()
            # FIX #8: Log detailed error information
            if resp.status == 200 and "id" in resp_data:
                BOT_STATE["fb_posts"] += 1
                logger.info(f"✅ FB Link Posted: {resp_data['id']}")
                return True
            else:
                # Log response data for debugging
                error_msg = resp_data.get('error', {}).get('message', 'Unknown')
                logger.error(f"❌ FB Link Failed: Status {resp.status}, Error: {error_msg}, Data: {resp_data}")
                # Enqueue for retry
                aid = await get_article_id(article['title'], article['link'])
                await db.add_failed_post(aid, "facebook", f"FBLinkError: {error_msg}", json.dumps(article))
    
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
        [InlineKeyboardButton("X (Twitter) 🐦", url=f"https://x.com/{config.X_USERNAME}")]
    ])
    
    msg = None
    
    # Try with photo
    if article.get("image_url"):
        # Validate image first
        if await validate_image(article["image_url"]):
            try:
                msg = await telegram_bot.send_photo(
                    chat_id=config.TELEGRAM_CHANNEL_ID,
                    photo=article["image_url"],
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=buttons
                )
                logger.info(f"✅ TG Photo Posted: {msg.message_id}")
            except Exception as e:
                # FIX #5: Track image failures
                BOT_STATE["image_failures"] += 1
                logger.warning(f"⚠️ TG Photo failed, trying text: {e}")
                msg = None
        else:
            # FIX #5: Track invalid images
            BOT_STATE["image_failures"] += 1
            logger.warning(f"⚠️ Invalid image: {article['image_url']}")
    
    # Fallback to text
    if not msg:
        try:
            msg = await telegram_bot.send_message(
                chat_id=config.TELEGRAM_CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=buttons,
                disable_web_page_preview=False
            )
            logger.info(f"✅ TG Text Posted: {msg.message_id}")
        except Exception as e:
            logger.error(f"❌ TG Post Failed: {e}")
            # Enqueue for retry
            aid = await get_article_id(article['title'], article['link'])
            await db.add_failed_post(aid, "telegram", str(type(e).__name__), json.dumps(article))
            return False
            
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

# =========================== RETRY WORKER ===========================

async def retry_worker():
    """Background task to process retry queue"""
    logger.info("🔄 Retry Worker Started")
    while True:
        try:
            await asyncio.sleep(300) # Check every 5 minutes
            
            pending = await db.get_pending_retries()
            if not pending: continue
            
            logger.info(f"🔄 Processing {len(pending)} retries...")
            
            for row in pending:
                id = row["id"]
                platform = row["platform"]
                retry_count = row["retry_count"]
                article = json.loads(row["article_data"])
                
                # Max retries (5)
                if retry_count >= 5:
                    logger.warning(f"💀 Dead Letter: {article['title'][:30]} ({platform})")
                    await db.update_retry_status(id, "DEAD")
                    continue
                
                logger.info(f"🔄 Retrying {platform} ({retry_count+1}/5): {article['title'][:30]}")
                
                success = False
                try:
                    if platform == "x":
                        success = await post_to_x(article, "🔄")
                    elif platform == "facebook":
                        success = await post_to_facebook(article, "🔄")
                    elif platform == "telegram":
                        success = await post_to_telegram(article, "🔄", False)
                except Exception as e:
                    logger.error(f"Retry failed: {e}")
                
                if success:
                    await db.update_retry_status(id, "SUCCESS")
                    logger.info(f"✅ Retry Successful: {article['title'][:30]}")
                else:
                    # Exponential Backoff: 1m, 5m, 15m, 1h, 6h
                    delays = [1, 5, 15, 60, 360]
                    delay = delays[min(retry_count, 4)]
                    await db.update_retry_status(id, "PENDING", retry_count + 1, delay)
                    
        except Exception as e:
            logger.error(f"❌ Retry Worker Error: {e}")
            await asyncio.sleep(60)

# FIX #2: Cleanup scheduler - runs every 24 hours
async def cleanup_scheduler():
    """Periodic database cleanup task"""
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)  # 24 hours
            logger.info("🧹 Starting scheduled DB cleanup...")
            await db.cleanup_old_records()
        except Exception as e:
            logger.error(f"❌ Cleanup scheduler error: { e}")

# =========================== WORKER ===========================

async def worker():
    """Main news processing loop"""
    # FIX #6: Removed config validation from here (moved to main block)
    await db.init_db()
    logger.info("🚀 MEGA NEWS BOT 2026 STARTED")
    
    # Initialize variables
    boost_until = None
    consecutive_errors = 0
    
    # Initial Cleanup
    await db.cleanup_old_records()
    
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
            
            # Get recent titles for duplicate check
            recent_titles = await db.get_recent_titles()
            
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
                        
                        # Initialize health stats if missing
                        if src["name"] not in BOT_STATE["sources_health"]:
                            BOT_STATE["sources_health"][src["name"]] = {'success': 0, 'fail': 0}
                            
                        if not feed:
                            BOT_STATE["sources_health"][src["name"]]["fail"] += 1
                            continue
                            
                        # Handle 304 Not Modified (Success but no new data)
                        if getattr(feed, "status", 200) == 304:
                            # logger.debug(f"📉 Feed 304: {src['name']}")
                            continue
                            
                        if not feed.entries: 
                            BOT_STATE["sources_health"][src["name"]]["fail"] += 1
                            continue
                        
                        BOT_STATE["sources_health"][src["name"]]["success"] += 1
                        e = feed.entries[0]
                        aid = await get_article_id(e.title, e.link)
                        
                        if await db.is_posted(aid): continue
                        
                        # Quality Check
                        q_score, q_reasons = scorer.score_article(article)
                        if q_score < 60:
                            logger.info(f"📉 Low Quality ({q_score}): {e.title[:30]}... Reasons: {', '.join(q_reasons)}")
                            continue
                            
                        # Duplicate Check
                        is_dup, match_title, score = detector.is_duplicate(e.title, recent_titles)
                        if is_dup:
                            logger.info(f"⏭️ Skipped Duplicate ({score:.2f}): {e.title[:30]}... == {match_title[:30]}...")
                            BOT_STATE["duplicate_skips"] += 1
                            await db.mark_as_posted(aid, e.title, cat, src["name"]) # Mark to skip future checks
                            continue

                        article = {
                            "title": e.title, "link": e.link,
                            "summary": BeautifulSoup(e.get("summary",""), "html.parser").get_text(strip=True)[:1000],
                            "image_url": get_image(e, src["url"]),
                            "source": src["name"]
                        }
                        
                        # Check breaking news
                        is_breaking = False
                        if config.is_breaking_news(article) and not boost_until:
                            logger.info("🚨 BREAKING NEWS DETECTED -> BOOST ON")
                            boost_until = now + timedelta(minutes=15)
                            emoji = "🚨 " + emoji
                            is_breaking = True
                        
                        # Translate (Rate Limit Check inside not needed as it's 15/min and we are slow)
                        if (await check_platform_rate_limit("gemini")) is None:
                            logger.warning("Gemini Rate Limit Hit - Skipping")
                            continue
                            
                        article = await translate(article)
                        
                        # Post to platforms with Rate Checks
                        fb_ok = False
                        if (await check_platform_rate_limit("facebook")) is not None:
                            fb_ok = await post_to_facebook(article, emoji)
                            
                        tg_ok = False
                        if (await check_platform_rate_limit("telegram")) is not None:
                            tg_ok = await post_to_telegram(article, emoji, is_breaking)
                            
                        x_ok = await post_to_x(article, emoji)

                        if fb_ok or tg_ok or x_ok:
                            await db.mark_as_posted(aid, article["title"], cat, src["name"])
                            recent_titles.append(article["title"]) # Update local cache
                            posted_count += 1
                            BOT_STATE["total_posted"] += 1
                            consecutive_errors = 0 # Reset error counter
                            
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
                        if src["name"] not in BOT_STATE["sources_health"]:
                            BOT_STATE["sources_health"][src["name"]] = {'success': 0, 'fail': 0}
                        BOT_STATE["sources_health"][src["name"]]["fail"] += 1
            
            # Calculate next run
            next_wait = 60 if boost_until else slot["delay"]
            next_time = (datetime.now(config.ICT) + timedelta(seconds=next_wait)).strftime("%H:%M:%S")
            BOT_STATE["next_run"] = next_time
            BOT_STATE["status"] = "Sleeping"
            
            logger.info(f"✓ Cycle done. Posted: {posted_count}. Next: {next_time}")
            
            try:
                await asyncio.wait_for(trigger_event.wait(), timeout=next_wait)
            except asyncio.TimeoutError:
                pass 

        except Exception as e:
            consecutive_errors += 1
            wait_time = min(300, 60 * (2 ** max(0, consecutive_errors - 5)))
            logger.error(f"Loop error (Count {consecutive_errors}): {e}. Waiting {wait_time}s")
            
            if consecutive_errors >= 5:
                await send_error_report(f"Persistent Worker Error ({consecutive_errors})", traceback.format_exc())
                
            await asyncio.sleep(wait_time)
        
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
            <div class="card"><h3>{x_posts}</h3><p>X / Twitter</p></div>
            <div class="card"><h3 style="color:orange">{duplicate_skips}</h3><p>Skips</p></div>
            <div class="card"><h3 style="color:red">{errors}</h3><p>Errors</p></div>
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
    
    return web.Response(text=HTML.format(
        status=BOT_STATE["status"],
        last_run=BOT_STATE["last_run"],
        next_run=BOT_STATE["next_run"],
        total_posted=BOT_STATE["total_posted"],
        fb_posts=BOT_STATE["fb_posts"],
        tg_posts=BOT_STATE["tg_posts"],
        x_posts=BOT_STATE["x_posts"],
        duplicate_skips=BOT_STATE["duplicate_skips"],
        errors=BOT_STATE["errors"],
        logs=logs_html
    ), content_type='text/html')

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
        worker(),
        cleanup_scheduler(),  # FIX #2: Add cleanup scheduler
        retry_worker()        # Retry System
    )

if __name__ == "__main__":
    # FIX #6: Config validation before asyncio.run
    try:
        config.validate_config()
        logger.info("✅ Config validated")
    except ValueError as e:
        logger.critical(f"❌ {e}")
        exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception:
        err = traceback.format_exc()
        logger.critical(f"💥 FATAL CRASH:\n{err}")
        
        # Send error report
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            send_error_report("FATAL CRASH DETECTED", err)
        )
        loop.close()