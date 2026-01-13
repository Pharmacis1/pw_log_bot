import struct
import os
from datetime import datetime

# [cite_start]Константы структуры файла [cite: 5]
HEADER_FORMAT = "<ii"      # 8 байт (from_id, to_id)
RECORD_FORMAT = "<iiiiiii"  # 28 байт (type, id, timestamp, who, p0, p1, p2)
RECORD_SIZE = 28

def parse_board_file(filepath):
    """Читает бинарный файл и возвращает список записей."""
    data_list = []
    
    if not os.path.exists(filepath):
        return []

    with open(filepath, 'rb') as f:
        # Пропускаем заголовок (8 байт)
        f.read(struct.calcsize(HEADER_FORMAT))

        while True:
            chunk = f.read(RECORD_SIZE)
            if len(chunk) < RECORD_SIZE:
                break
            
            # [cite_start]Распаковываем байты в числа [cite: 5]
            rtype, rid, ts, role_id, p0, p1, p2 = struct.unpack(RECORD_FORMAT, chunk)
            
            # Фильтр: игнорируем даты из 1970 года (пустые записи)
            if ts < 1600000000: # Отсекаем всё, что старше ~2020 года
                continue
                
            try:
                dt = datetime.fromtimestamp(ts)
                dt_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                dt_str = "Error Date"

            desc = decode_action(rtype, role_id, p0, p1, p2)
            
            data_list.append({
                "date": dt_str,
                "timestamp": ts,
                "role_id": role_id,
                "action_type": rtype,
                "description": desc,
                "raw_params": f"{p0}, {p1}, {p2}"
            })
            
    # Сортируем: новые сверху
    data_list.sort(key=lambda x: x['timestamp'], reverse=True)
    return data_list

def decode_action(rtype, who, p0, p1, p2):
    """Расшифровка кодов действий на основе FactionBoard.c"""
    # [cite_start]См. switch(record->type) в FactionBoard.c [cite: 8]
    if rtype == 0: return f"Получил предмет ID {p0}"
    if rtype == 1: return f"Вклад (Доблесть): {p0}"
    if rtype == 2: return f"Вклад (Золото): {p0}"
    if rtype == 5: return f"Пригласил игрока ID {p0}"
    if rtype == 6: return "Вступил в гильдию"
    if rtype == 7: return "Отказался вступить"
    if rtype == 8: return "Покинул гильдию"
    if rtype == 9: 
        # [cite_start]p1 - роль, p2 - направление (1=повысил, иначе понизил) [cite: 8]
        role_map = {2: "Мастер", 3: "Маршал", 4: "Майор", 5: "Капитан", 6: "Рядовой"}
        role = role_map.get(p1, str(p1))
        act = "Повысил" if p2 == 1 else "Понизил"
        return f"{act} ID {p0} до {role}"
    if rtype == 10: return f"Изгнал ID {p0}"
    
    return f"Действие {rtype}"