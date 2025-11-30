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
                    
                    # Migration: Add title column if missing
                    try:
                        await db.execute("ALTER TABLE posted ADD COLUMN title TEXT")
                        logger.info("⚠️ Migrated DB: Added 'title' column")
                    except Exception:
                        pass # Column likely exists
                    
                    # Translation Cache Table
                    await db.execute("""
                        CREATE TABLE IF NOT EXISTS translations (
                            article_id TEXT PRIMARY KEY,
                            title_kh TEXT,
                            body_kh TEXT,
                            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    await db.commit()
            logger.info("✅ Database initialized (Posted + Cache)")
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

async def cleanup_old_records(days: int = 30):
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            await db.execute("DELETE FROM posted WHERE posted_at < datetime('now', ?)", (f'-{days} days',))
            await db.execute("DELETE FROM translations WHERE cached_at < datetime('now', ?)", (f'-{days} days',))
            await db.commit()
            logger.info("🧹 DB Cleanup Completed")

async def get_translation(aid: str):
    for attempt in range(3):
        try:
            async with db_lock:
                async with aiosqlite.connect(config.DB_FILE) as db:
                    cur = await db.execute("SELECT title_kh, body_kh FROM translations WHERE article_id=?", (aid,))
                    row = await cur.fetchone()
                    if row: return {"title_kh": row[0], "body_kh": row[1]}
            return None
        except Exception as e:
            logger.warning(f"⚠️ DB get_translation failed (Attempt {attempt+1}/3): {e}")
            await asyncio.sleep(2)
    logger.error("❌ DB get_translation FAILED after 3 attempts")
    return None

async def save_translation(aid: str, title_kh: str, body_kh: str):
    for attempt in range(3):
        try:
            async with db_lock:
                async with aiosqlite.connect(config.DB_FILE) as db:
                    await db.execute("INSERT OR REPLACE INTO translations(article_id, title_kh, body_kh) VALUES(?, ?, ?)", (aid, title_kh, body_kh))
                    await db.commit()
            return
        except Exception as e:
            logger.warning(f"⚠️ DB save_translation failed (Attempt {attempt+1}/3): {e}")
            await asyncio.sleep(2)
    logger.error("❌ DB save_translation FAILED after 3 attempts")
