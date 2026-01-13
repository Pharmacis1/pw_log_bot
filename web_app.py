from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import aiosqlite
from datetime import datetime, timedelta, timezone
import shutil
import os
from typing import List
from fastapi import UploadFile, File, Query
from fastapi.staticfiles import StaticFiles
# Подгружаем парсер. Если он в той же папке - отлично.
try:
    from board_parser import parse_board_file
except ImportError:
    pass # Обработаем если надо, но предполагаем что он есть
from consts import CLASSES


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB_NAME = "clan_archive.db"

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def get_last_update_time():
    """Получает дату самой свежей записи в БД и конвертирует в МСК (UTC+3)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT MAX(timestamp) FROM events")
        row = await cursor.fetchone()
        ts = row[0]
        if ts:
            # 1. Получаем дату как UTC (независимо от сервера)
            dt_utc = datetime.fromtimestamp(ts, timezone.utc)
            # 2. Добавляем ровно 3 часа (МСК)
            dt_msk = dt_utc + timedelta(hours=3)
            return dt_msk.strftime('%d.%m.%Y %H:%M') + " (МСК)"
    return "Нет данных"

def analyze_stats(events):
    """
    Анализирует список событий игрока.
    Возвращает словарь со всеми счетчиками (золото, доблесть, этапы).
    """
    stats = {
        "s1": 0, "s2": 0, "s3": 0, "s4": 0, "s5": 0, "s6": 0, "s7": 0,
        "adepts": 0, "dances": 0,
        "total_gold": 0,
        "total_valor": 0
    }
    
    events.sort(key=lambda x: x[0])
    
    for i, (ts, val, etype) in enumerate(events):
        # Золото
        if etype == 2:
            stats['total_gold'] += val
            continue 
            
        # Доблесть
        if etype == 1:
            stats['total_valor'] += val
            
            # Этапы КХ
            if val == 4:
                is_dance = False
                # Проверка назад (< 20 мин)
                if i > 0:
                    prev_ts, prev_val, prev_type = events[i-1]
                    if prev_type == 1 and prev_val == 2 and (ts - prev_ts) < 1200:
                        is_dance = True
                
                # Проверка вперед (< 20 мин)
                if not is_dance and i < len(events) - 1:
                    next_ts, next_val, next_type = events[i+1]
                    if next_type == 1 and next_val == 8 and (next_ts - ts) < 1200:
                        is_dance = True
                
                if is_dance: stats['dances'] += 1
                else: stats['s1'] += 1
            
            elif val == 6: stats['s2'] += 1
            elif val == 10: stats['s3'] += 1
            elif val == 14: stats['s4'] += 1
            elif val == 24: stats['s5'] += 1
            elif val == 40: stats['s6'] += 1
            elif val == 70: stats['s7'] += 1
            elif val == 7: stats['adepts'] += 1
            elif val in [2, 8]: stats['dances'] += 1
            
    return stats

async def get_data_from_db(start_date: str = None, end_date: str = None, classes: List[int] = None):
    today = datetime.now()
    if not end_date: end_date = today.strftime('%Y-%m-%d')
    
    # Авто-выбор: Понедельник текущей недели
    if not start_date:
        days_to_subtract = today.weekday()
        monday = today - timedelta(days=days_to_subtract)
        start_date = monday.strftime('%Y-%m-%d')

    async with aiosqlite.connect(DB_NAME) as conn:
        # Базовый SQL
        sql = """
            SELECT 
                p.role_id, 
                COALESCE(p.nickname, 'ID ' || p.role_id), 
                p.class_id,
                e.timestamp, 
                e.value, 
                e.event_type
            FROM players p
            LEFT JOIN events e ON p.role_id = e.role_id 
                AND e.event_type IN (1, 2)
                AND substr(e.event_date, 1, 10) >= ? 
                AND substr(e.event_date, 1, 10) <= ?
            WHERE p.in_clan = 1
        """
        params = [start_date, end_date]
        
        # Фильтр по классам
        if classes:
            placeholders = ",".join("?" * len(classes))
            sql += f" AND p.class_id IN ({placeholders})"
            params.extend(classes)

        cursor = await conn.execute(sql, tuple(params))
        raw_rows = await cursor.fetchall()

    # Группировка
    players_events = {}
    for rid, name, cid, ts, val, etype in raw_rows:
        if rid not in players_events:
            players_events[rid] = {"name": name, "class_id": cid, "events": []}
        players_events[rid]["events"].append((ts, val, etype))

    result = []
    for rid, data in players_events.items():
        stats = analyze_stats(data["events"])
        stats["name"] = data["name"]
        
        # Mapping Class
        cid = data["class_id"]
        if cid in CLASSES:
            cname, cemoji, cshort = CLASSES[cid]
            stats["class_icon"] = f"/static/icons/{cid}.png"
            stats["class_name"] = cname
        else:
            stats["class_icon"] = ""
            stats["class_name"] = ""
            
        result.append(stats)

    # Сортировка: Сначала по 7 этапу, потом по общей доблести
    result.sort(key=lambda x: (x['s7'], x['total_valor']), reverse=True)
    
    return result, start_date, end_date

# --- ROUTES (МАРШРУТЫ) ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, start: str = None, end: str = None, classes: List[int] = Query(None)):
    if start == "": start = None
    if end == "": end = None
    
    rows, s_date, e_date = await get_data_from_db(start, end, classes)
    
    # --- История (все события с учетом фильтра по датам) ---
    async with aiosqlite.connect(DB_NAME) as conn:
        # Показываем ВСЕ типы событий: вклады золота/доблести, предметы, гильдийные действия
        sql_history = """
            SELECT 
                e.event_date,
                COALESCE(p.nickname, 'ID ' || e.role_id) as name,
                p.class_id,
                e.raw_desc,
                e.event_type,
                e.role_id
            FROM events e
            LEFT JOIN players p ON e.role_id = p.role_id
            WHERE substr(e.event_date, 1, 10) >= ? 
              AND substr(e.event_date, 1, 10) <= ?
        """
        params = [s_date, e_date]
        if classes:
            placeholders = ",".join("?" * len(classes))
            sql_history += f" AND p.class_id IN ({placeholders})"
            params.extend(classes)
            
        sql_history += " ORDER BY e.timestamp DESC"
        
        cursor = await conn.execute(sql_history, tuple(params))
        raw_history = await cursor.fetchall()

    history_rows = []
    for date, name, cid, desc, etype, role_id in raw_history:
        # emoji = CLASSES.get(cid, ("", "", ""))[1] if cid is not None else ""
        icon_url = f"/static/icons/{cid}.png" if cid is not None and cid in CLASSES else ""
        cname = CLASSES[cid][0] if cid is not None and cid in CLASSES else ""
        history_rows.append((date, name, icon_url, cname, desc, etype, role_id))
    
    last_upd = await get_last_update_time()
    
    # Подготовка списка классов для фильтра
    # CLASSES format: {id: (name, emoji, short)}
    all_classes_list = []
    for cid, (cname, cemoji, cshort) in CLASSES.items():
        all_classes_list.append({
            "id": cid,
            "name": cname,
            "icon": f"/static/icons/{cid}.png",
            "selected": (cid in classes) if classes else False
        })
    # Сортировка по ID
    all_classes_list.sort(key=lambda x: x['id'])

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "rows": rows, 
        "current_start": s_date, 
        "current_end": e_date,
        "last_updated": last_upd,
        "history_rows": history_rows,
        "all_classes": all_classes_list,
        "selected_classes": classes or [],
        "CLASSES": CLASSES  # Для модального окна редактирования
    })

@app.get("/download/watcher")
async def download_watcher():
    exe_path = "dist/PW_Requiem_history.exe"
    zip_path = "dist/PW_Requiem_history.zip"
    
    if not os.path.exists(exe_path):
        return {"error": "Exe file not found. Please build it first."}

    # Проверяем, нужно ли обновлять архив (если архива нет или exe новее)
    create_zip = False
    if not os.path.exists(zip_path):
        create_zip = True
    else:
        exe_mtime = os.path.getmtime(exe_path)
        zip_mtime = os.path.getmtime(zip_path)
        if exe_mtime > zip_mtime:
            create_zip = True
            
    if create_zip:
        try:
            import zipfile
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(exe_path, arcname="PW_Requiem_history.exe")
        except Exception as e:
            return {"error": f"Failed to create zip: {str(e)}"}

    return FileResponse(path=zip_path, filename="PW_Requiem_history.zip", media_type='application/zip')

@app.post("/api/upload")
async def upload_log(file: UploadFile = File(...)):
    """API endpoint для загрузки логов через утилиту"""
    temp_path = f"temp_upload_{file.filename}"
    
    try:
        # 1. Сохраняем файл
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 2. Парсим
        data = parse_board_file(temp_path)
        if not data:
            return {"status": "error", "message": "File empty or data too old"}
            
        new_events = 0
        
        # 3. Пишем в БД (Логика идентична боту)
        async with aiosqlite.connect(DB_NAME) as conn:
            cursor = await conn.cursor()
            
            for row in data:
                rid = row['role_id']
                etype = row['action_type']
                desc = row['description'].lower()
                val = 0
                if row['raw_params']:
                    try:
                        val = int(row['raw_params'].split(',')[0])
                    except: pass

                # Игрок
                await cursor.execute("INSERT OR IGNORE INTO players (role_id, in_clan) VALUES (?, 1)", (rid,))
                
                # Статус
                is_leave = "покинул" in desc or "изгнан" in desc or "вышел" in desc
                if is_leave:
                    await cursor.execute("UPDATE players SET in_clan = 0 WHERE role_id = ?", (rid,))
                elif etype in [1, 2] or "принят" in desc or "joined" in desc:
                    await cursor.execute("UPDATE players SET in_clan = 1 WHERE role_id = ?", (rid,))
                
                # Событие
                await cursor.execute("""
                    INSERT INTO events (role_id, timestamp, event_date, event_type, value, raw_desc)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (rid, row['timestamp'], row['date'], etype, val, row['description']))
                
                if cursor.rowcount > 0:
                    new_events += 1
                    
            await conn.commit()
            
        return {"status": "ok", "new_events": new_events, "total_parsed": len(data)}

    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/api/update_nickname")
async def update_nickname(request: Request):
    """API endpoint для обновления никнейма игрока"""
    try:
        data = await request.json()
        role_id = data.get('role_id')
        nickname = data.get('nickname', '').strip()
        
        if not role_id:
            return {"status": "error", "message": "role_id is required"}
        
        async with aiosqlite.connect(DB_NAME) as conn:
            # Проверяем существование игрока
            async with conn.execute("SELECT 1 FROM players WHERE role_id = ?", (role_id,)) as cursor:
                if not await cursor.fetchone():
                    return {"status": "error", "message": f"Player ID {role_id} not found"}
            
            # Обновляем никнейм (пустая строка = NULL)
            if nickname:
                await conn.execute("UPDATE players SET nickname = ? WHERE role_id = ?", (nickname, role_id))
            else:
                await conn.execute("UPDATE players SET nickname = NULL WHERE role_id = ?", (role_id,))
            await conn.commit()
            
        return {"status": "ok", "message": f"Nickname updated for ID {role_id}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/update_class")
async def update_class(request: Request):
    """API endpoint для обновления класса игрока"""
    try:
        data = await request.json()
        role_id = data.get('role_id')
        class_id = data.get('class_id')
        
        if not role_id:
            return {"status": "error", "message": "role_id is required"}
        
        # Проверяем валидность class_id
        if class_id is not None and class_id not in CLASSES and class_id != -1:
            return {"status": "error", "message": f"Invalid class_id: {class_id}"}
        
        async with aiosqlite.connect(DB_NAME) as conn:
            # Проверяем существование игрока
            async with conn.execute("SELECT 1 FROM players WHERE role_id = ?", (role_id,)) as cursor:
                if not await cursor.fetchone():
                    return {"status": "error", "message": f"Player ID {role_id} not found"}
            
            # Обновляем класс
            await conn.execute("UPDATE players SET class_id = ? WHERE role_id = ?", (class_id, role_id))
            await conn.commit()
            
        class_name = CLASSES.get(class_id, ("Неизвестно", "", ""))[0] if class_id in CLASSES else "Не указан"
        return {"status": "ok", "message": f"Class updated for ID {role_id} to {class_name}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

