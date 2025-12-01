import asyncio
import aiosqlite
import config

async def check_db():
    async with aiosqlite.connect(config.DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        
        print("--- Pending Posts ---")
        async with db.execute("SELECT id, title, status, priority FROM pending_posts") as cur:
            rows = await cur.fetchall()
            for row in rows:
                print(f"[{row['status']}] P{row['priority']}: {row['title']}")
            if not rows: print("No pending posts.")

        print("\n--- Failed Posts ---")
        async with db.execute("SELECT id, platform, status, error_type FROM failed_posts") as cur:
            rows = await cur.fetchall()
            for row in rows:
                print(f"[{row['status']}] {row['platform']}: {row['error_type']}")
            if not rows: print("No failed posts.")
            
        print("\n--- Posted ---")
        async with db.execute("SELECT COUNT(*) FROM posted") as cur:
            count = (await cur.fetchone())[0]
            print(f"Total Posted: {count}")

if __name__ == "__main__":
    asyncio.run(check_db())
