"""
Extractor кандидатов для лабораторных бланков МЕДСИ.

МЕДСИ-формат (pypdf inline):
  (WBC) Лейкоциты 10*9/л 4.50-11.004.78
  (RBC) Эритроциты 10*12/л 4.30-5.705.33
  СОЭ мм/час 0-15↑ 35

Проблема: pypdf извлекает столбцы inline, и значение склеивается
с концом референсного диапазона:
  "4.50-11.004.78"  →  ref="4.50-11.00" + value="4.78"
  "150-400213"      →  ref="150-400"    + value="213"

Этот модуль:
  - детектирует формат МЕДСИ
  - корректно разделяет ref и value
  - формирует TSV-кандидаты (name\tvalue\tref\tunit)

ВАЖНО: helix_table_to_candidates и baseline-парсер НЕ затрагиваются.
"""

import re
from typing import Optional, Tuple, List


# ──────────────────────────────────────────────
# Маппинг МЕДСИ-кодов → стандартные коды проекта
# ──────────────────────────────────────────────
_CODE_BASE_MAP = {
    "NEU": "NE",
    "LYM": "LY",
    "MONO": "MO",
    "EOS": "EO",
    "BAS": "BA",
}


def _map_medsi_code(raw_code: str) -> str:
    """
    Приводит МЕДСИ-специфичные коды к стандартным:
      NEU% → NE%,  LYM# → LY,  MONO% → MO%  и т.п.
    """
    code = raw_code.strip()
    if not code:
        return code
    suffix = ""
    if code.endswith("%") or code.endswith("#"):
        suffix = code[-1]
        base = code[:-1]
    else:
        base = code
    mapped = _CODE_BASE_MAP.get(base.upper(), base.upper())
    return mapped + suffix


# ──────────────────────────────────────────────
# Единицы измерения МЕДСИ (от длинных к коротким)
# ──────────────────────────────────────────────
_MEDSI_UNITS = [
    "10*12/л", "10*9/л",
    "мм/час", "мм/ч",
    "г/дл", "г/л",
    "фл.", "фл",
    "пг",
    "%",
]
_UNITS_RE = "|".join(re.escape(u) for u in _MEDSI_UNITS)


# ──────────────────────────────────────────────
# ДЕТЕКТОР ФОРМАТА МЕДСИ
# ──────────────────────────────────────────────
def is_medsi_format(raw_text: str) -> bool:
    """
    True, если текст похож на бланк МЕДСИ:
      - >= 5 строк начинаются с (CODE)
      ИЛИ есть одновременно '10*9' и '10*12'
      ИЛИ 'СОЭ' + 'мм/час' + >= 2 строк (CODE)
    И при этом НЕТ заголовков Хеликс-таблицы.
    """
    if not raw_text:
        return False

    # Исключение: Хеликс-формат с табуляциями
    if "Исследование\tРезультат" in raw_text or "Тест\tРезультат" in raw_text:
        return False

    lines = raw_text.splitlines()
    code_re = re.compile(r"^\s*\([A-Za-zА-Яа-я\-#%0-9]+\)\s")
    code_count = sum(1 for l in lines if code_re.match(l))

    has_10_9 = "10*9" in raw_text
    has_10_12 = "10*12" in raw_text
    has_soe = "СОЭ" in raw_text
    has_mmch = "мм/час" in raw_text

    if code_count >= 5:
        return True
    if has_10_9 and has_10_12:
        return True
    if has_soe and has_mmch and code_count >= 2:
        return True

    return False


# ──────────────────────────────────────────────
# РАЗДЕЛЕНИЕ СКЛЕЕННОГО REF + VALUE
# ──────────────────────────────────────────────
def _split_ref_and_value(ref_val: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Разделяет склеенную строку REF_LOW-REF_HIGH[↑↓]VALUE.

    Алгоритм:
      1. Извлечь ref_low (число до дефиса).
      2. Посчитать кол-во десятичных знаков ref_low → dp.
      3. Для dp>0: ref_high — ровно dp знаков после точки.
         Для dp==0:
           a) если после цифр есть нецифровой символ (↑, ↓, пробел) — разделитель;
           b) иначе — эвристика: ref_high имеет столько же цифр, что и ref_low.
      4. Остаток (с убранными флагами ↑↓) — это value.

    Возвращает (ref_text, value_str) или (None, None).
    """
    s = (ref_val or "").strip()
    if not s:
        return None, None

    # Нормализуем дефисы
    s = s.replace("–", "-").replace("—", "-")

    m = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(.*)", s)
    if not m:
        return None, None

    ref_low_str = m.group(1)
    after_dash = m.group(2)
    if not after_dash:
        return s, None

    ref_low = float(ref_low_str)

    # Десятичные знаки ref_low
    dp = len(ref_low_str.split(".")[1]) if "." in ref_low_str else 0

    ref_high_str: Optional[str] = None
    remainder = ""

    if dp > 0:
        # Дробные числа: ref_high имеет ровно dp десятичных знаков
        pat = re.compile(r"^(\d+\.\d{" + str(dp) + r"})(.*)")
        m2 = pat.match(after_dash)
        if m2:
            ref_high_str = m2.group(1)
            remainder = m2.group(2)
    else:
        # Целые числа
        # a) Проверяем, есть ли естественный разделитель (↑↓ или пробел после цифр)
        flag_m = re.match(r"^(\d+)\s*([↑↓!])(.*)", after_dash)
        if flag_m:
            ref_high_str = flag_m.group(1)
            remainder = flag_m.group(2) + flag_m.group(3)
        else:
            # b) Все цифры подряд → эвристика по кол-ву цифр ref_low
            n = len(ref_low_str)
            # Пробуем разные длины ref_high: n, n+1, n-1, n+2
            for nd in [n, n + 1, n - 1, n + 2]:
                if nd < 1 or nd > len(after_dash):
                    continue
                cand = after_dash[:nd]
                rest = after_dash[nd:]
                if not re.match(r"^\d+$", cand):
                    continue
                try:
                    if float(cand) >= ref_low:
                        ref_high_str = cand
                        remainder = rest
                        break
                except ValueError:
                    continue

    if ref_high_str is None:
        return s, None

    # Убираем флаги и пробелы из remainder → value
    remainder = re.sub(r"^[\s↑↓!]+", "", remainder)

    value_str: Optional[str] = None
    if remainder:
        val_m = re.match(r"^(\d+(?:[.,]\d+)?)", remainder)
        if val_m:
            value_str = val_m.group(1).replace(",", ".")

    ref_text = f"{ref_low_str}-{ref_high_str}"
    return ref_text, value_str


# ──────────────────────────────────────────────
# ШУМОВЫЕ СТРОКИ
# ──────────────────────────────────────────────
_NOISE_KEYWORDS = [
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
]


def _is_noise(line: str) -> bool:
    low = line.lower()
    return any(kw in low for kw in _NOISE_KEYWORDS)


# ──────────────────────────────────────────────
# СКЛЕЙКА СТРОК-ПРОДОЛЖЕНИЙ (для pypdf)
# ──────────────────────────────────────────────
def _join_medsi_continuations(lines: List[str]) -> List[str]:
    """
    Склеивает строки-продолжения в pypdf-формате МЕДСИ.

    Если строка начинается с (CODE) но не содержит ref-диапазон
    (число-число), значит имя показателя разбито на 2+ строк.
    Соединяем их, пока не найдём ref.
    """
    result: List[str] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Строка-кандидат: начинается с (CODE) или с 'СОЭ'
        starts_with_code = bool(re.match(r"^\([A-Za-zА-Яа-я\-#%0-9]+\)", line))
        starts_with_soe = bool(re.match(r"^СОЭ\s", line, re.IGNORECASE))

        # Также: строки без (CODE) но с единицей и ref
        has_ref = bool(re.search(r"\d+(?:\.\d+)?\s*-\s*\d", line))

        if (starts_with_code or starts_with_soe) and not has_ref:
            # Неполная строка — склеиваем с последующими
            combined = line
            j = i + 1
            while j < len(lines):
                next_l = lines[j].strip()
                if not next_l:
                    j += 1
                    continue
                combined = combined + " " + next_l
                j += 1
                if re.search(r"\d+(?:\.\d+)?\s*-\s*\d", combined):
                    break
            result.append(combined)
            i = j
        else:
            result.append(line)
            i += 1

    return result


# ──────────────────────────────────────────────
# ПАРСЕР ОДНОЙ INLINE-СТРОКИ
# ──────────────────────────────────────────────
def _try_parse_inline(line: str) -> Optional[str]:
    """
    Парсит одну inline-строку pypdf МЕДСИ:
      "(WBC) Лейкоциты 10*9/л 4.50-11.004.78"
    Возвращает TSV-кандидат: "name\\tvalue\\tref\\tunit"
    """
    line = line.strip()
    if not line or _is_noise(line):
        return None

    # Ищем единицу измерения с пробелом перед ней (чтобы не ловить % внутри кода)
    unit_match = None
    for u in _MEDSI_UNITS:
        # Ищем ' unit ' или ' unit' в конце → единица окружена пробелами
        pattern = re.compile(r"\s(" + re.escape(u) + r")\s")
        m = pattern.search(line)
        if m:
            unit_match = (m.start(1), m.end(1), u)
            break

    if not unit_match:
        return None

    u_start, u_end, unit = unit_match
    name_part = line[:u_start].strip()
    after_unit = line[u_end:].strip()

    if not name_part or not after_unit:
        return None

    # Проверяем наличие ref-диапазона
    if not re.search(r"\d+(?:\.\d+)?\s*-\s*\d", after_unit):
        return None

    ref_text, value_str = _split_ref_and_value(after_unit)
    if not ref_text or value_str is None:
        return None

    # Очищаем имя: извлекаем код, маппим МЕДСИ→стандарт
    clean_name = _clean_medsi_name(name_part)

    return f"{clean_name}\t{value_str}\t{ref_text}\t{unit}"


def _clean_medsi_name(raw_name: str) -> str:
    """
    Очищает имя показателя из МЕДСИ:
      '(NEU%) Нейтрофилы'  →  'Нейтрофилы (NE%)'
      '(WBC) Лейкоциты'    →  'Лейкоциты (WBC)'
      'СОЭ'                →  'СОЭ'
    """
    m = re.match(r"^\(([A-Za-zА-Яа-я\-#%0-9]+)\)\s*(.*)", raw_name)
    if m:
        raw_code = m.group(1)
        russian = m.group(2).strip()
        std_code = _map_medsi_code(raw_code)
        if russian:
            return f"{russian} ({std_code})"
        return f"({std_code})"
    # Без кода — оставляем как есть
    return raw_name


# ──────────────────────────────────────────────
# ПАРСЕР OCR MULTILINE (вторичный)
# ──────────────────────────────────────────────
def _parse_medsi_ocr_multiline(raw_text: str) -> List[str]:
    """
    Парсит OCR-формат МЕДСИ, где столбцы на отдельных строках:
      (WBC) Лейкоциты
      4.78
      10*9/л
      4.50-11.00
    """
    lines = [l.strip() for l in (raw_text or "").splitlines() if l.strip()]
    lines = [l for l in lines if not re.match(r"^---\s*PAGE\s+\d+\s*---", l)]

    candidates: List[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        is_name = bool(re.match(r"^\([A-Za-zА-Яа-я\-#%0-9]+\)", line))
        is_soe = bool(re.match(r"^соэ$", line, re.IGNORECASE))

        if not (is_name or is_soe):
            i += 1
            continue

        name = line
        value_str: Optional[str] = None
        unit: Optional[str] = None
        ref_text: Optional[str] = None

        j = i + 1
        # Собираем данные из следующих 1-6 строк
        limit = min(i + 7, len(lines))
        while j < limit:
            nl = lines[j].strip()
            if not nl:
                j += 1
                continue

            # Это новое имя? Прекращаем сбор
            if re.match(r"^\([A-Za-zА-Яа-я\-#%0-9]+\)", nl):
                break

            # Значение? (число, возможно с "...")
            val_clean = nl.rstrip(".").replace(",", ".")
            if value_str is None and re.match(r"^-?\d+(?:\.\d+)?$", val_clean):
                value_str = val_clean
                j += 1
                continue

            # Единица?
            if unit is None:
                nl_clean = nl.rstrip(".")
                for u in _MEDSI_UNITS:
                    if nl_clean == u or nl.startswith(u):
                        unit = u
                        break
                if unit is not None:
                    j += 1
                    continue

            # Референс? (число-число)
            ref_m = re.match(r"^(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?)", nl)
            if ref_m:
                ref_text = ref_m.group(1).replace(" ", "")
                j += 1
                break

            # Продолжение имени (кириллические слова без цифр)
            if re.match(r"^[а-яА-Я]", nl) and not re.search(r"\d", nl):
                name = name + " " + nl
                j += 1
                continue

            j += 1

        if value_str and ref_text:
            clean_name = _clean_medsi_name(name)
            candidates.append(f"{clean_name}\t{value_str}\t{ref_text}\t{unit or ''}")

        i = j if j > i else i + 1

    return candidates


# ──────────────────────────────────────────────
# ГЛАВНАЯ ФУНКЦИЯ
# ──────────────────────────────────────────────
def medsi_inline_to_candidates(raw_text: str) -> str:
    """
    Извлекает TSV-кандидаты из текста МЕДСИ (любого формата).

    Два прохода:
      1. Inline (pypdf): строки вида  '(CODE) Name UNIT REF+VALUE'
      2. Multiline (OCR): столбцы на отдельных строках

    Возвращает TSV (name\\tvalue\\tref\\tunit), совместимый
    с parse_items_from_candidates.
    """
    if not raw_text:
        return ""

    # Убираем маркеры страниц (если есть)
    text = re.sub(r"---\s*PAGE\s+\d+\s*---", "", raw_text)
    lines_raw = [l for l in text.splitlines() if l.strip()]

    # ─── Pass 1: Inline (pypdf) ───
    joined = _join_medsi_continuations(lines_raw)
    inline_cands: List[str] = []
    for line in joined:
        cand = _try_parse_inline(line)
        if cand:
            inline_cands.append(cand)

    # Если inline дал >= 10 кандидатов — хватает
    if len(inline_cands) >= 10:
        return "\n".join(inline_cands)

    # ─── Pass 2: OCR multiline ───
    ocr_cands = _parse_medsi_ocr_multiline(raw_text)

    # Объединяем, дедуплицируем по имени (первый столбец)
    all_cands = inline_cands + ocr_cands
    seen: set = set()
    result: List[str] = []
    for c in all_cands:
        key = c.split("\t")[0].strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(c)

    return "\n".join(result)





