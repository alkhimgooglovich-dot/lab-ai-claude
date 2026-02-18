"""
Скоринг строк OCR / text-layer для определения полезности.

score_line(line) → float 0..1
    Чем выше — тем вероятнее, что строка содержит лабораторный показатель.

Функции-предикаты:
    has_numeric_value(line) — содержит ли числовое значение
    has_ref_pattern(line)   — содержит ли паттерн референса (число-число, <=, >=)
    has_known_unit(line)    — содержит ли известную единицу измерения
    has_known_biomarker(line) — содержит ли известный биомаркер
    is_noise(line)          — является ли служебной / мусорной строкой
"""

import re
from typing import Set

from parsers.unit_dictionary import is_valid_unit

# ──────────────────────────────────────────────
# Известные биомаркеры (коды + русские фрагменты)
# ──────────────────────────────────────────────
_BIOMARKER_CODES: Set[str] = {
    "WBC", "RBC", "HGB", "HCT", "PLT", "MCV", "MCH", "MCHC",
    "RDW", "PDW", "MPV", "PCT",
    "NEU", "LYM", "MONO", "EOS", "BAS",
    "NE", "LY", "MO", "EO", "BA",
    "ALT", "AST", "GGT", "ALP",
    "TBIL", "DBIL", "IBIL",
    "CREA", "UREA", "CRP", "CRPN",
    "GLUC", "GLU", "HBA1C",
    "CHOL", "HDL", "LDL", "TRIG",
    "TSH", "FT3", "FT4", "T3", "T4",
    "FE", "FERR", "VIT",
    "ESR", "СОЭ",
    "P-LCR",
}

_BIOMARKER_RUS_FRAGMENTS = [
    "лейкоцит", "эритроцит", "гемоглоб", "гематокрит",
    "тромбоцит", "нейтрофил", "лимфоцит", "моноцит",
    "эозинофил", "базофил", "скорость оседания", "соэ",
    "глюкоз", "холестерин", "билирубин", "креатинин",
    "мочевин", "белок общ", "альбумин", "ферритин",
    "железо", "витамин",
]

# ──────────────────────────────────────────────
# Шумовые маркеры (начало строки, lowercase)
# ──────────────────────────────────────────────
_NOISE_PREFIXES = (
    "информация в интернете",
    "лицензия",
    "eqas",
    "riqas",
    "фсвок",
    "iso",
    "отчет создан",
    "отчёт создан",
    "страница",
    "подтверждение",
    "результаты анализов",
    "интерпретацию полученных",
    "* время указано",
    "** референсные",
    "метод и оборудование",
    "общеклинический анализ",
    "название/показатель",
    "название показателя",
    "референсные значения",
    "global group",
    "заказ №",
    "заказ no",
    "sgs",
    "образец №",
    "обазец №",
    "зарегистрирован",
    "валидация",
    "место взятия",
    # МЕДСИ-шум
    "исследование -",
    "наименование",
    "выполнено по",
    "врач:",
    "фамилия:",
    "имя:",
    "отчество:",
    "дата:",
    "номер заказа",
    "биоматериал",
    "клинический анализ",
    "медси",
    "www.medsi",
    "медицина компетенций",
    "врач кдл",
    "дата рождения",
    "пол:",
    "лпу:",
    "карта:",
    "отделение:",
    "хорошёвский",
    "группа компаний",
    "+7",
    "пациент:",
    "печать:",
    "подпись:",
    "результаты:",
    "№ направления",
    "ед. изм.",
    "нормальные значения",
)


# ──────────────────────────────────────────────
# Предикаты
# ──────────────────────────────────────────────
def has_numeric_value(line: str) -> bool:
    """Содержит ли строка числовое значение (целое или дробное)."""
    return bool(re.search(r"(?<![A-Za-z])\d+(?:[.,]\d+)?", line))


def has_ref_pattern(line: str) -> bool:
    """Содержит ли строка паттерн референса: число-число, <=N, >=N, до N."""
    s = (line or "").replace("–", "-").replace("—", "-")
    if re.search(r"\d+(?:[.,]\d+)?\s*-\s*\d+(?:[.,]\d+)?", s):
        return True
    if re.search(r"(<=|>=|<|>|≤|≥)\s*\d+(?:[.,]\d+)?", s):
        return True
    if re.search(r"(?:^|\s)[Дд]о\s*\d+(?:[.,]\d+)?", s):
        return True
    return False


def has_known_unit(line: str) -> bool:
    """Содержит ли строка известную единицу измерения."""
    s = (line or "").strip()
    if not s:
        return False
    # Ищем слова и фрагменты, которые могут быть единицей
    tokens = re.split(r"\s+", s)
    for t in tokens:
        t_clean = t.strip(".,;:()")
        if t_clean and is_valid_unit(t_clean):
            return True
    # Специальная проверка: *10^N/л, 10*N/л
    if re.search(r"10[\^*]\d+/л", s):
        return True
    return False


def has_known_biomarker(line: str) -> bool:
    """Содержит ли строка известный биомаркер (код или русское название)."""
    s = (line or "").strip()
    if not s:
        return False
    # Коды (латиница, в скобках или отдельно)
    codes_in_line = re.findall(r"\b([A-Za-z][A-Za-z0-9\-]{1,8}(?:%|#)?)\b", s)
    for code in codes_in_line:
        if code.upper() in _BIOMARKER_CODES:
            return True
    # Код в скобках: (WBC), (NEU%)
    bracket_codes = re.findall(r"\(([A-Za-zА-Яа-я\-#%0-9]+)\)", s)
    for code in bracket_codes:
        if code.upper().rstrip("#%") in _BIOMARKER_CODES:
            return True
    # Русские фрагменты
    low = s.lower()
    for frag in _BIOMARKER_RUS_FRAGMENTS:
        if frag in low:
            return True
    return False


def is_header_service_line(line: str) -> bool:
    """
    Расширенная проверка «шапочных» / служебных строк PDF.
    Такие строки не содержат лабораторных показателей и должны
    отсеиваться на этапе фильтрации кандидатов.

    Проверяемые категории:
      - Телефон (+7 / 8-800 …)
      - Email
      - URL / сайт
      - ИНН, ОГРН, КПП
      - Адрес (г., ул., пр., д. …)
      - Номер заказа / направления (№ NNNNN)
      - Дата/время БЕЗ биомаркера
      - QR / штрихкод (длинная цифровая строка > 12 цифр)
      - ФИО пациента / врача (Иванов И.И.)
    """
    s = (line or "").strip()
    if not s:
        return False  # пустые строки обрабатывает is_noise()

    low = s.lower()

    # --- Телефон ---
    if re.search(r"(\+7|8[\s\-]?\(?\d)[\d\s()\-]{7,}", s):
        # Не фильтруем, если строка содержит биомаркер
        if not has_known_biomarker(s):
            return True

    # --- Email ---
    if re.search(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}", s):
        return True

    # --- URL / сайт ---
    if re.search(r"(https?://|www\.)", low):
        return True

    # --- ИНН ---
    if re.search(r"инн\s*\d{10,12}", low):
        return True

    # --- ОГРН ---
    if re.search(r"огрн\s*\d{13,15}", low):
        return True

    # --- КПП ---
    if re.search(r"кпп\s*\d{9}", low):
        return True

    # --- Адрес ---
    if re.match(r"^(г\.|ул\.|пр\.|д\.|корп\.|стр\.|пом\.)", low):
        return True
    if "адрес:" in low:
        return True

    # --- Номер заказа / направления (№ с 5+ цифрами) ---
    if re.match(r"^№\s*\d{5,}", s):
        return True

    # --- Дата/время БЕЗ биомаркера ---
    # Сначала проверяем строгие форматы «чистой даты» (вся строка — дата/время)
    if re.match(r"^\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2}(:\d{2})?)?$", s):
        return True
    if re.match(r"^\d{2}\.\d{2}\.\d{4}(\s+\d{2}:\d{2}(:\d{2})?)?$", s):
        return True
    # Общая проверка: строка содержит дату, но не содержит биомаркер / единицу / реф
    has_date = bool(re.search(r"\d{2}\.\d{2}\.\d{4}", s)) or bool(re.search(r"\d{4}-\d{2}-\d{2}", s))
    if has_date and not has_known_biomarker(s):
        if not has_known_unit(s) and not has_ref_pattern(s):
            return True

    # --- QR / штрихкод: только цифры, длина > 12 ---
    if re.match(r"^\d{13,}$", s):
        return True

    # --- ФИО-формат: Иванов И.И. ---
    if re.match(r"^[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.$", s):
        return True

    return False


def is_noise(line: str) -> bool:
    """Является ли строка служебной / мусорной."""
    s = (line or "").strip()
    if not s:
        return True
    low = s.lower()
    # Слишком короткая строка без цифр
    if len(s) < 3:
        return True
    # Шумовые префиксы
    for prefix in _NOISE_PREFIXES:
        if low.startswith(prefix):
            return True
    # Только цифры (номера страниц, заказов и т.д.) без буквенного контекста
    if re.match(r"^\d+$", s):
        return True
    # Маркер страницы
    if re.match(r"^---\s*PAGE\s+\d+\s*---$", s, re.IGNORECASE):
        return True
    # Расширенная проверка шапочных / служебных строк
    if is_header_service_line(s):
        return True
    return False


def is_unit_only_line(line: str) -> bool:
    """
    Проверяет, является ли строка чистой единицей измерения.
    Примеры: "г/л", "*10^9/л", "ммоль/л", "%"
    """
    s = (line or "").strip()
    if not s or len(s) > 20:
        return False
    # Содержит числа (кроме *10^N) — не чистый unit
    if has_numeric_value(s) and not re.match(r"^\*?10[\^*]\d+", s):
        return False
    # Проверяем через unit_dictionary
    s_clean = s.strip(".,;:()")
    if s_clean and is_valid_unit(s_clean):
        return True
    # Проверяем шаблоны: *10^N/л
    if re.match(r"^\*?10\s*[\^*]\s*\d+/[а-яa-z]+$", s, re.IGNORECASE):
        return True
    return False


# ──────────────────────────────────────────────
# Скоринг строки
# ──────────────────────────────────────────────
def score_line(line: str) -> float:
    """
    Оценивает строку по шкале 0..1:
        0.0 — мусор / шум
        0.2 — есть числа, но больше ничего
        0.4 — есть числа + что-то (единица или имя маркера)
        0.6 — есть числа + референс
        0.8 — есть числа + референс + единица или маркер
        1.0 — полный набор: число, референс, единица, маркер

    Порог отсечения для кандидата в universal_extractor: >= 0.4
    """
    s = (line or "").strip()
    if not s:
        return 0.0

    if is_noise(s):
        return 0.0

    score = 0.0

    _has_num = has_numeric_value(s)
    _has_ref = has_ref_pattern(s)
    _has_unit = has_known_unit(s)
    _has_bio = has_known_biomarker(s)

    if _has_num:
        score += 0.2

    if _has_ref:
        score += 0.3

    if _has_unit:
        score += 0.2

    if _has_bio:
        score += 0.3

    # Если строка начинается с числа (без имени) — вероятно, это value-line,
    # а не самодостаточный кандидат → снижаем
    if re.match(r"^\s*[↑↓+]?\s*\d", s) and not _has_bio:
        score = max(0.0, score - 0.1)

    return min(1.0, round(score, 2))


