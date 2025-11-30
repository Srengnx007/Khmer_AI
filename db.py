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
                            category TEXT,
                            source TEXT,
                            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
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
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
            return await cur.fetchone() is not None

async def mark_as_posted(aid: str, cat: str, source: str):
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            await db.execute("INSERT OR IGNORE INTO posted(article_id, category, source) VALUES(?, ?, ?)", (aid, cat, source))
            await db.commit()

async def get_translation(aid: str):
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            cur = await db.execute("SELECT title_kh, body_kh FROM translations WHERE article_id=?", (aid,))
            row = await cur.fetchone()
            if row: return {"title_kh": row[0], "body_kh": row[1]}
    return None

async def save_translation(aid: str, title_kh: str, body_kh: str):
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            await db.execute("INSERT OR REPLACE INTO translations(article_id, title_kh, body_kh) VALUES(?, ?, ?)", (aid, title_kh, body_kh))
            await db.commit()
