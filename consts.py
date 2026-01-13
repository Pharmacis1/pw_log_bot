
# PW Class Mapping
# ID -> (Name, Emoji, ShortName)
CLASSES = {
    0: ("Воин", "⚔️", "WR"),
    1: ("Маг", "🔥", "MG"),
    2: ("Шаман", "🔮", "PSY"),
    3: ("Друид", "🦊", "DR"),
    4: ("Оборотень", "🐯", "WB"),
    5: ("Убийца", "🗡️", "SIN"),
    6: ("Лучник", "🏹", "EA"),
    7: ("Жрец", "🪽", "EP"),
    8: ("Страж", "👁️", "SK"),
    9: ("Мистик", "🌿", "MS"),
    10: ("Призрак", "🌑", "DB"),
    11: ("Жнец", "🌙", "SB"),
    12: ("Стрелок", "🔫", "GS"),
    13: ("Паладин", "🛡️", "PAL"),
    14: ("Странник", "🐵", "MY"),
    15: ("Бард", "🎵", "BRD"),
    16: ("Дух крови", "🩸", "VAMP")
}

CLASS_BY_NAME = {}
for cid, (name, emoji, short) in CLASSES.items():
    CLASS_BY_NAME[name.lower()] = cid
    CLASS_BY_NAME[short.lower()] = cid
    CLASS_BY_NAME[str(cid)] = cid
