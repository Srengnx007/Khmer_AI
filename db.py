import aiosqlite
import asyncio
import logging
import config

logger = logging.getLogger(__name__)
db_lock = asyncio.Lock()

async def init_db():
    for attempt in range(3):
        try:
            async with db_lock:
                async with aiosqlite.connect(config.DB_FILE) as db:
                    # Posted Articles Table
                    await db.execute("""
                        CREATE TABLE IF NOT EXISTS posted (
                            article_id TEXT PRIMARY KEY,
                            title TEXT,
                            category TEXT,
                            source TEXT,
                            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # FIX #9: Safe migration - Check if 'title' column exists before adding
                    cur = await db.execute("PRAGMA table_info(posted)")
                    columns = [row[1] for row in await cur.fetchall()]
                    if 'title' not in columns:
                        await db.execute("ALTER TABLE posted ADD COLUMN title TEXT")
                        logger.info("✅ Migrated DB: Added 'title' column")
                    
                    # Translation Cache Table
                    await db.execute("""
                        CREATE TABLE IF NOT EXISTS translations (
                            article_id TEXT PRIMARY KEY,
                            title_kh TEXT,
                            body_kh TEXT,
                            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    # Retry Queue Table
                    await db.execute("""
                        CREATE TABLE IF NOT EXISTS failed_posts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            article_id TEXT,
                            platform TEXT,
                            error_type TEXT,
                            retry_count INTEGER DEFAULT 0,
                            next_retry TIMESTAMP,
                            status TEXT DEFAULT 'PENDING', -- PENDING, RETRYING, FAILED, DEAD
                            article_data TEXT, -- JSON serialized article
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    await db.commit()
            logger.info("✅ Database initialized (Posted + Cache + Retry Queue)")
            return
        except Exception as e:
            logger.warning(f"⚠️ DB Init failed (Attempt {attempt+1}/3): {e}")
            await asyncio.sleep(2)
    logger.critical("❌ Database initialization FAILED after 3 attempts!")

async def is_posted(aid: str) -> bool:
    for attempt in range(3):
        try:
            async with db_lock:
                async with aiosqlite.connect(config.DB_FILE) as db:
                    cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
                    return await cur.fetchone() is not None
        except Exception as e:
            logger.warning(f"⚠️ DB is_posted failed (Attempt {attempt+1}/3): {e}")
            await asyncio.sleep(2)
    logger.error("❌ DB is_posted FAILED after 3 attempts")
    return False

async def mark_as_posted(aid: str, title: str, cat: str, source: str):
    for attempt in range(3):
        try:
            async with db_lock:
                async with aiosqlite.connect(config.DB_FILE) as db:
                    await db.execute("INSERT OR IGNORE INTO posted(article_id, title, category, source) VALUES(?, ?, ?, ?)", (aid, title, cat, source))
                    await db.commit()
            return
        except Exception as e:
            logger.warning(f"⚠️ DB mark_as_posted failed (Attempt {attempt+1}/3): {e}")
            await asyncio.sleep(2)
    logger.error("❌ DB mark_as_posted FAILED after 3 attempts")

async def get_recent_titles(hours: int = 24):
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            cur = await db.execute(
                "SELECT title FROM posted WHERE posted_at > datetime('now', ?)", 
                (f'-{hours} hours',)
            )
            return [row[0] for row in await cur.fetchall() if row[0]]

async def cleanup_old_records():
    """Delete records older than 30 days"""
    try:
        async with db_lock:
            async with aiosqlite.connect(config.DB_FILE) as db:
                await db.execute("DELETE FROM posted WHERE posted_at < datetime('now', '-30 days')")
                await db.execute("DELETE FROM translations WHERE cached_at < datetime('now', '-30 days')")
                await db.execute("DELETE FROM failed_posts WHERE status='DEAD' AND created_at < datetime('now', '-7 days')")
                await db.commit()
        logger.info("🧹 DB Cleanup complete")
    except Exception as e:
        logger.error(f"❌ DB Cleanup failed: {e}")

# =========================== TRANSLATION CACHE ===========================

async def get_translation(aid: str):
    """Get cached translation"""
    try:
        async with db_lock:
            async with aiosqlite.connect(config.DB_FILE) as db:
                async with db.execute("SELECT title_kh, body_kh FROM translations WHERE article_id=?", (aid,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return {"title_kh": row[0], "body_kh": row[1]}
    except Exception as e:
        logger.error(f"❌ DB Cache Get Error: {e}")
    return None

async def save_translation(aid: str, title_kh: str, body_kh: str):
    """Save translation to cache"""
    try:
        async with db_lock:
            async with aiosqlite.connect(config.DB_FILE) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO translations(article_id, title_kh, body_kh) VALUES(?, ?, ?)",
                    (aid, title_kh, body_kh)
                )
                await db.commit()
    except Exception as e:
        logger.error(f"❌ DB Cache Save Error: {e}")

# =========================== RETRY QUEUE ===========================

async def add_failed_post(aid: str, platform: str, error_type: str, article_data: str):
    """Add failed post to retry queue"""
    try:
        async with db_lock:
            async with aiosqlite.connect(config.DB_FILE) as db:
                # Check if already exists and pending
                cur = await db.execute(
                    "SELECT id FROM failed_posts WHERE article_id=? AND platform=? AND status IN ('PENDING', 'RETRYING')",
                    (aid, platform)
                )
                if await cur.fetchone():
                    return # Already queued
                
                # Initial retry in 1 minute
                next_retry = "datetime('now', '+1 minute')"
                
                await db.execute("""
                    INSERT INTO failed_posts(article_id, platform, error_type, article_data, next_retry)
                    VALUES(?, ?, ?, ?, datetime('now', '+1 minute'))
                """, (aid, platform, error_type, article_data))
                await db.commit()
                logger.info(f"📥 Added to Retry Queue: {aid} ({platform})")
    except Exception as e:
        logger.error(f"❌ Failed to add to retry queue: {e}")

async def get_pending_retries():
    """Get posts due for retry"""
    try:
        async with db_lock:
            async with aiosqlite.connect(config.DB_FILE) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("""
                    SELECT * FROM failed_posts 
                    WHERE status='PENDING' AND next_retry <= datetime('now')
                    LIMIT 10
                """)
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Failed to get pending retries: {e}")
        return []

async def update_retry_status(id: int, status: str, retry_count: int = 0, next_delay_minutes: int = 0):
    """Update retry status and schedule next retry"""
    try:
        async with db_lock:
            async with aiosqlite.connect(config.DB_FILE) as db:
                if status == 'PENDING':
                    # Schedule next retry
                    await db.execute("""
                        UPDATE failed_posts 
                        SET status=?, retry_count=?, next_retry=datetime('now', ?)
                        WHERE id=?
                    """, (status, retry_count, f'+{next_delay_minutes} minutes', id))
                else:
                    # Final status (FAILED/DEAD/SUCCESS)
                    await db.execute("UPDATE failed_posts SET status=? WHERE id=?", (status, id))
                
                await db.commit()
    except Exception as e:
        logger.error(f"❌ Failed to update retry status: {e}")
