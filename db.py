import aiosqlite
import asyncio
import logging
import json
import config
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class DatabasePool:
    """
    Simple connection pool for aiosqlite.
    Since SQLite is file-based, we limit concurrency to avoid lock contention.
    WAL mode allows multiple readers, but still one writer.
    """
    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = asyncio.Queue(maxsize=max_connections)
        self.created_connections = 0
        self.lock = asyncio.Lock() # Global lock for write operations if needed, but we rely on WAL

    async def init_pool(self):
        """Initialize the pool with connections"""
        # We don't pre-fill, we create on demand up to max
        pass

    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool"""
        conn = None
        try:
            # Try to get from queue
            if self.pool.empty() and self.created_connections < self.max_connections:
                async with self.lock:
                    if self.created_connections < self.max_connections:
                        conn = await aiosqlite.connect(self.db_path)
                        # Enable WAL mode for better concurrency
                        await conn.execute("PRAGMA journal_mode=WAL;")
                        await conn.execute("PRAGMA synchronous=NORMAL;")
                        await conn.commit()
                        self.created_connections += 1
            
            if not conn:
                conn = await self.pool.get()
            
            yield conn
            
        finally:
            if conn:
                # Reset connection state if needed? SQLite doesn't have much state.
                # Put back in pool
                try:
                    self.pool.put_nowait(conn)
                except asyncio.QueueFull:
                    # Should not happen if logic is correct
                    await conn.close()
                    async with self.lock:
                        self.created_connections -= 1

    async def close(self):
        """Close all connections"""
        while not self.pool.empty():
            conn = await self.pool.get()
            await conn.close()

# Global Pool
db_pool = DatabasePool(config.DB_FILE, max_connections=5)

async def init_db():
    """Initialize Database Schema"""
    async with db_pool.acquire() as db:
        try:
            # Enable WAL
            await db.execute("PRAGMA journal_mode=WAL;")
            
            # Posted Articles Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS posted (
                    article_id TEXT PRIMARY KEY,
                    title TEXT,
                    category TEXT,
                    source TEXT,
                    language TEXT DEFAULT 'km',
                    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Migration: Add language column if missing
            try:
                await db.execute("ALTER TABLE posted ADD COLUMN language TEXT DEFAULT 'km'")
            except Exception:
                pass # Column likely exists
            
            # Indexes for performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_posted_at ON posted(posted_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_source ON posted(source)")
            
            # Translation Cache Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS translation_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id TEXT,
                    language TEXT,
                    content TEXT, -- JSON serialized {title, body, summary}
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(article_id, language)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trans_cache ON translation_cache(article_id, language)")
            
            # Pending Posts Queue
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id TEXT,
                    title TEXT,
                    link TEXT,
                    summary TEXT,
                    image_url TEXT,
                    source TEXT,
                    category TEXT,
                    priority INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'PENDING',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_posts(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_priority ON pending_posts(priority DESC, created_at ASC)")
            
            # Retry Queue Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS failed_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id TEXT,
                    platform TEXT,
                    error_type TEXT,
                    retry_count INTEGER DEFAULT 0,
                    next_retry TIMESTAMP,
                    status TEXT DEFAULT 'PENDING',
                    article_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_failed_next_retry ON failed_posts(next_retry) WHERE status='PENDING'")
            
            await db.commit()
            
            # Run VACUUM to optimize
            await db.execute("VACUUM;")
            
            logger.info("✅ Database initialized (WAL Mode + Indexes + VACUUM)")
            
        except Exception as e:
            logger.critical(f"❌ Database initialization FAILED: {e}")
            raise e

async def is_posted(aid: str) -> bool:
    async with db_pool.acquire() as db:
        async with db.execute("SELECT 1 FROM posted WHERE article_id=?", (aid,)) as cur:
            if await cur.fetchone(): return True
        
        async with db.execute("SELECT 1 FROM pending_posts WHERE article_id=?", (aid,)) as cur:
            if await cur.fetchone(): return True
            
    return False

async def mark_as_posted(aid: str, title: str, cat: str, source: str, lang: str = 'km'):
    async with db_pool.acquire() as db:
        await db.execute(
            "INSERT OR IGNORE INTO posted(article_id, title, category, source, language) VALUES(?, ?, ?, ?, ?)", 
            (aid, title, cat, source, lang)
        )
        await db.commit()

async def get_recent_titles(hours: int = 24):
    async with db_pool.acquire() as db:
        async with db.execute(
            "SELECT title FROM posted WHERE posted_at > datetime('now', ?)", 
            (f'-{hours} hours',)
        ) as cur:
            return [row[0] for row in await cur.fetchall() if row[0]]

async def cleanup_old_records():
    """Delete records older than 30 days"""
    try:
        async with db_pool.acquire() as db:
            await db.execute("DELETE FROM posted WHERE posted_at < datetime('now', '-30 days')")
            await db.execute("DELETE FROM translation_cache WHERE cached_at < datetime('now', '-30 days')")
            await db.execute("DELETE FROM failed_posts WHERE status='DEAD' AND created_at < datetime('now', '-7 days')")
            await db.execute("DELETE FROM pending_posts WHERE status='PROCESSED' AND created_at < datetime('now', '-1 days')")
            await db.commit()
            await db.execute("VACUUM;") # Reclaim space
        logger.info("🧹 DB Cleanup & VACUUM complete")
    except Exception as e:
        logger.error(f"❌ DB Cleanup failed: {e}")

# =========================== TRANSLATION CACHE ===========================

async def get_translation(aid: str, lang: str):
    try:
        async with db_pool.acquire() as db:
            async with db.execute("SELECT content FROM translation_cache WHERE article_id=? AND language=?", (aid, lang)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row[0])
    except Exception as e:
        logger.error(f"❌ DB Cache Get Error: {e}")
    return None

async def save_translation(aid: str, lang: str, content: dict):
    try:
        async with db_pool.acquire() as db:
            await db.execute(
                "INSERT OR REPLACE INTO translation_cache(article_id, language, content) VALUES(?, ?, ?)",
                (aid, lang, json.dumps(content))
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ DB Cache Save Error: {e}")

# =========================== RETRY QUEUE ===========================

async def add_failed_post(aid: str, platform: str, error_type: str, article_data: str):
    try:
        async with db_pool.acquire() as db:
            # Check if already exists and pending
            async with db.execute(
                "SELECT id FROM failed_posts WHERE article_id=? AND platform=? AND status IN ('PENDING', 'RETRYING')",
                (aid, platform)
            ) as cur:
                if await cur.fetchone(): return

            await db.execute("""
                INSERT INTO failed_posts(article_id, platform, error_type, article_data, next_retry)
                VALUES(?, ?, ?, ?, datetime('now', '+1 minute'))
            """, (aid, platform, error_type, article_data))
            await db.commit()
            logger.info(f"📥 Added to Retry Queue: {aid} ({platform})")
    except Exception as e:
        logger.error(f"❌ Failed to add to retry queue: {e}")

async def get_pending_retries():
    try:
        async with db_pool.acquire() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM failed_posts 
                WHERE status='PENDING' AND next_retry <= datetime('now')
                LIMIT 10
            """) as cur:
                return await cur.fetchall()
    except Exception as e:
        logger.error(f"❌ Failed to get pending retries: {e}")
        return []

async def update_retry_status(id: int, status: str, retry_count: int = 0, next_delay_minutes: int = 0):
    try:
        async with db_pool.acquire() as db:
            if status == 'PENDING':
                await db.execute("""
                    UPDATE failed_posts 
                    SET status=?, retry_count=?, next_retry=datetime('now', ?)
                    WHERE id=?
                """, (status, retry_count, f'+{next_delay_minutes} minutes', id))
            else:
                await db.execute("UPDATE failed_posts SET status=? WHERE id=?", (status, id))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Failed to update retry status: {e}")

# =========================== PENDING POSTS (SCHEDULER) ===========================

async def add_pending_post(article: dict, priority: int = 1):
    try:
        async with db_pool.acquire() as db:
            await db.execute("""
                INSERT INTO pending_posts(article_id, title, link, summary, image_url, source, category, priority)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article.get('article_id'), article['title'], article['link'], 
                article['summary'], article.get('image_url'), article['source'], 
                article.get('category', 'General'), priority
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Failed to add pending post: {e}")

async def get_next_pending_post():
    try:
        async with db_pool.acquire() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM pending_posts 
                WHERE status='PENDING'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            """) as cur:
                return await cur.fetchone()
    except Exception as e:
        logger.error(f"❌ Failed to get next pending post: {e}")
        return None

async def mark_pending_processed(id: int):
    try:
        async with db_pool.acquire() as db:
            await db.execute("UPDATE pending_posts SET status='PROCESSED' WHERE id=?", (id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Failed to mark pending processed: {e}")
