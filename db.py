import aiosqlite
import asyncio
import logging
import config

logger = logging.getLogger(__name__)
db_lock = asyncio.Lock()

async def init_db():
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
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
        async with aiosqlite.connect(config.DB_FILE) as db:
            cur = await db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,))
            return await cur.fetchone() is not None

async def mark_as_posted(aid: str, cat: str, source: str):
    async with db_lock:
        async with aiosqlite.connect(config.DB_FILE) as db:
            await db.execute("INSERT OR IGNORE INTO posted(article_id, category, source) VALUES(?, ?, ?)", (aid, cat, source))
            await db.commit()
