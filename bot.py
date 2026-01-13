import asyncio
import os
import csv
import aiosqlite
import logging
import sys

from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from dotenv import load_dotenv
from aiogram.types import BufferedInputFile 
import io
from aiogram.types import FSInputFile, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from consts import CLASSES, CLASS_BY_NAME


# Настройка логирования (чтобы видеть ошибки в консоли)
logging.basicConfig(level=logging.INFO)

# Импортируем наш парсер
try:
    from board_parser import parse_board_file
except ImportError as e:
    logging.error(f"❌ ОШИБКА ИМПОРТА: {e}")
    logging.error("Убедись, что файл называется board_parser.py и лежит рядом с bot.py")
    sys.exit(1)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Проверка токена
if not TOKEN:
    logging.error("❌ ОШИБКА: Не найден токен в файле .env")
    sys.exit(1)

try:
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
except Exception as e:
    logging.error(f"❌ ОШИБКА ПРИ СОЗДАНИИ БОТА: {e}")
    sys.exit(1)

DB_NAME = "clan_archive.db"

async def init_db():
    """Создает таблицы и обновляет структуру при необходимости."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.cursor()
        
        # 1. Таблица ИГРОКОВ
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                role_id INTEGER PRIMARY KEY,
                nickname TEXT DEFAULT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                in_clan INTEGER DEFAULT 1,
                class_id INTEGER DEFAULT -1
            )
        """)
        
        # --- МИГРАЦИЯ: Если таблицы старые, добавляем колонку in_clan ---
        try:
            await cursor.execute("ALTER TABLE players ADD COLUMN in_clan INTEGER DEFAULT 1")
            logging.info("🛠 Добавлена колонка in_clan в таблицу players")
        except Exception: 
            pass 

        # --- МИГРАЦИЯ: Добавляем class_id ---
        try:
            await cursor.execute("ALTER TABLE players ADD COLUMN class_id INTEGER DEFAULT -1")
            logging.info("🛠 Добавлена колонка class_id в таблицу players")
        except Exception:
            pass
            
        # 2. Таблица СОБЫТИЙ
        await cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_id INTEGER,
                timestamp INTEGER,
                event_date TEXT,
                event_type INTEGER, 
                value INTEGER,
                raw_desc TEXT,
                UNIQUE(role_id, timestamp, event_type) ON CONFLICT IGNORE
            )
        """)
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON events (event_date)")
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_type ON events (event_type)")
        await conn.commit()
        
    logging.info("💾 База данных инициализирована и проверена.")
# --- ХЭНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Вставь СЮДА свою ссылку от ngrok
    WEB_APP_URL = os.getenv("WEB_APP_URL")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Открыть Архив (Mini App)", web_app=WebAppInfo(url=WEB_APP_URL))]
    ])

    await message.answer(
        "👋 Привет! Я **Бот-Архивариус**.\n\n"
        "📂 Кидай файлы `FactionBoard...` сюда, чтобы пополнять базу.\n"
        "👇 Нажми кнопку, чтобы увидеть красивую таблицу.\n\n"
        "⚙️ **Доступные команды:**\n\n"
        "🔹 `/name [ID] [Никнейм]` — привязать никнейм к ID игрока\n"
        "   Пример: `/name 123456 SuperGamer`\n\n"
        "🔹 `/class [ID] [Класс]` — привязать класс (профессию) к игроку\n"
        "   Пример: `/class 123456 WB` или `/class 123456 Воин`\n\n"
        "💡 Узнать ID игрока можно во вкладке 📜 История в веб-приложении",
        reply_markup=kb
    )

@dp.message(F.document)
async def handle_file(message: types.Message):
    doc = message.document
    if not doc.file_name.startswith("FactionBoard"):
        return await message.answer("⚠️ Кидай только файлы, начинающиеся на `FactionBoard`.")

    temp_path = f"temp_{doc.file_name}"
    await bot.download(doc, destination=temp_path)
    
    try:
        data = parse_board_file(temp_path)
        logging.info(f"📂 Распаршено записей из файла: {len(data)}")
        
        if not data:
            return await message.answer("❌ Файл пуст, не содержит записей или все записи слишком старые (фильтр 2020+).")

        new_events = 0
        new_players = 0
        

        async with aiosqlite.connect(DB_NAME) as conn:
            cursor = await conn.cursor()
            
            for row in data:
                rid = row['role_id']
                etype = row['action_type']
                desc = row['description'].lower() # Текст события маленькими буквами
                
                # 1. Добавляем игрока (или обновляем, если он уже есть)
                # По умолчанию считаем, что если он в логах - он был в клане
                await cursor.execute("INSERT OR IGNORE INTO players (role_id, in_clan) VALUES (?, 1)", (rid,))
                if cursor.rowcount > 0:
                    new_players += 1
                
                # --- ЛОГИКА СТАТУСА (В КЛАНЕ / ВЫШЕЛ) ---
                
                # Сценарий А: Игрок ВЫШЕЛ или ИЗГНАН
                # Ищем слова "покинул", "изгнан", "leave", "quit", "kicked"
                # А также проверяем типы событий (обычно 5, 6, 201, 202 - зависит от версии)
                is_leave_event = False
                if "покинул" in desc or "изгнан" in desc or "вышел" in desc:
                    is_leave_event = True
                # Если у тебя английский сервер: if "left" in desc or "kicked" in desc:
                
                if is_leave_event:
                    await cursor.execute("UPDATE players SET in_clan = 0 WHERE role_id = ?", (rid,))
                
                # Сценарий Б: Игрок ПРИНЯТ или СДЕЛАЛ ВКЛАД
                # Если есть запись о вкладе (тип 1, 2) или вступлении (обычно 3, 4) - значит он ВНУТРИ
                elif etype in [1, 2] or "принят" in desc or "joined" in desc:
                    await cursor.execute("UPDATE players SET in_clan = 1 WHERE role_id = ?", (rid,))
                
                # ----------------------------------------

                # 2. Определяем Value (как и раньше)
                params = list(map(int, row['raw_params'].split(',')))
                val = params[0] if params else 0
                
                # 3. Пишем событие
                await cursor.execute("""
                    INSERT INTO events (role_id, timestamp, event_date, event_type, value, raw_desc)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (rid, row['timestamp'], row['date'], etype, val, row['description']))
                
                if cursor.rowcount > 0:
                    new_events += 1
            await conn.commit()
        
        text = (
            f"📥 **Импорт завершен!**\n"
            f"📊 Найдено в файле: <b>{len(data)}</b>\n"
            f"🆕 Новых событий: <b>{new_events}</b>\n"
            f"👤 Новых ID в базе: <b>{new_players}</b>\n\n"
            f"База растёт! 📈"
        )
        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка обработки файла: {e}")
        await message.answer(f"Ошибка: {e}")
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)


@dp.message(Command("report"))
async def cmd_report(message: types.Message):
    """Генерирует CSV с суммой вкладов по дням (надежный метод)"""
    
    # 1. Достаем данные
    async with aiosqlite.connect(DB_NAME) as conn:
        sql = """
            SELECT 
                p.role_id,
                COALESCE(p.nickname, 'Unknown ID'),
                substr(e.event_date, 1, 10) as day,
                SUM(CASE WHEN e.event_type = 2 THEN e.value ELSE 0 END) as gold,
                SUM(CASE WHEN e.event_type = 1 THEN e.value ELSE 0 END) as valor
            FROM events e
            LEFT JOIN players p ON e.role_id = p.role_id
            WHERE e.event_type IN (1, 2)
            GROUP BY p.role_id, day
            ORDER BY day DESC, gold DESC
        """
        cursor = await conn.execute(sql)
        rows = await cursor.fetchall()

    logging.info(f"📊 Запрос к БД вернул строк: {len(rows)}")

    if not rows:
        return await message.answer("📭 В базе нет записей о вкладах.")

    # 2. Пишем в байтовый буфер (BytesIO)
    output_bytes = io.BytesIO()
    # Оборачиваем байтовый поток в текстовый для CSV
    text_wrapper = io.TextIOWrapper(output_bytes, encoding='utf-8-sig', newline='')
    
    writer = csv.writer(text_wrapper, delimiter=';')
    writer.writerow(["Role_ID", "Ник", "Дата", "Золото", "Доблесть"])
    writer.writerows(rows)
    
    # ВАЖНО: Сбрасываем данные из текстовой обертки в байтовый буфер
    text_wrapper.flush()
    # Перематываем буфер в начало (на всякий случай)
    output_bytes.seek(0)
    
    # Получаем чистые байты
    file_data = output_bytes.getvalue()
    
    logging.info(f"📦 Размер сформированного файла: {len(file_data)} байт")

    # 3. Отправляем
    filename = f"report_{datetime.now().strftime('%Y%m%d')}.csv"
    file = BufferedInputFile(file_data, filename=filename)
    
    await message.answer_document(file, caption=f"📊 Отчет: {len(rows)} строк.")

@dp.message(Command("name"))
async def cmd_set_name(message: types.Message):
    try:
        # /name 123456 SuperNagibator
        _, rid, nick = message.text.split(maxsplit=2)

        async with aiosqlite.connect(DB_NAME) as conn:
            await conn.execute("UPDATE players SET nickname = ? WHERE role_id = ?", (nick, rid))
            await conn.commit()
        await message.answer(f"✅ ID {rid} теперь известен как <b>{nick}</b>", parse_mode="HTML")
    except:
        await message.answer("Формат: `/name 123456 Никнейм`", parse_mode="Markdown")

@dp.message(Command("class"))
async def cmd_set_class(message: types.Message):
    try:
        # /class 123456 WB
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            raise ValueError("Not enough args")
            
        _, rid, class_str = args
        class_str = class_str.lower()
        
        if class_str not in CLASS_BY_NAME:
            available = ", ".join([v[2] for v in CLASSES.values()])
            await message.answer(f"❌ Неизвестный класс. Доступные: {available}")
            return

        cid = CLASS_BY_NAME[class_str]
        cname, cemoji, cshort = CLASSES[cid]

        async with aiosqlite.connect(DB_NAME) as conn:
            # Проверяем, есть ли такой ID
            async with conn.execute("SELECT 1 FROM players WHERE role_id = ?", (rid,)) as cursor:
                if not await cursor.fetchone():
                    await message.answer(f"⚠️ ID {rid} не найден в базе. Сначала загрузите логи.")
                    return

            await conn.execute("UPDATE players SET class_id = ? WHERE role_id = ?", (cid, rid))
            await conn.commit()
            
        await message.answer(f"✅ Для ID {rid} установлен класс: {cemoji} <b>{cname}</b>", parse_mode="HTML")
    except Exception as e:
        await message.answer("Формат: `/class ID Класс`\nПример: `/class 1024 WB` или `/class 1024 Воин`")

async def main():
    print(">>> Запуск бота...")
    await init_db()
    print("💾 База данных подключена/создана.")
    
    # Удаляем вебхуки
    await bot.delete_webhook(drop_pending_updates=True)
    
    print(">>> Бот запущен! (Нажми Ctrl+C для остановки)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(">>> Бот остановлен.")
    except Exception as e:
        logging.critical(f"!!! КРИТИЧЕСКАЯ ОШИБКА: {e}")