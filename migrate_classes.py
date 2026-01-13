import asyncio
import aiosqlite

DB_NAME = "clan_archive.db"

async def migrate():
    print(f"Connecting to {DB_NAME}...")
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.cursor()
        try:
            await cursor.execute("ALTER TABLE players ADD COLUMN class_id INTEGER DEFAULT -1")
            print("✅ Added 'class_id' column to 'players' table.")
            await conn.commit()
        except Exception as e:
            print(f"ℹ️ {e} (Column might already exist)")

if __name__ == "__main__":
    asyncio.run(migrate())
