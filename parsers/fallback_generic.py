"""
Fallback-парсер: универсальный split_value_unit_ref(rest).

ВАЖНО:
  - Этот модуль НЕ используется, если baseline-парсер уже успешно распознал показатели.
  - Он применяется ТОЛЬКО к строкам-кандидатам (фильтр: строка содержит норму в конце).
  - Fallback НЕ изменяет baseline-логику и работает только когда baseline провалился.
"""

import re
import sys
from pathlib import Path
from typing import Optional, List, Tuple

# Чтобы можно было импортировать из корня проекта
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engine import (
    Item, Range, parse_float, parse_ref_range, status_by_range,
    normalize_name, clean_raw_name, _dbg,
)


def split_value_unit_ref(rest: str) -> Tuple[Optional[float], str, str]:
    """
    Универсальный разбор строки вида:
        "8.23 *10^9/л 4.00 - 10.00"
        "28 мм/ч 2 - 20"
        "120 г/л 117 - 155"
        "34.7 % 35.0 - 45.0"

    Возвращает (value, unit, ref_text) или (None, "", "") если не удалось разобрать.
    """
    rest = re.sub(r"\s+", " ", (rest or "").strip())
    if not rest:
        return None, "", ""

    # Нормализуем дефисы
    rest = rest.replace("–", "-").replace("—", "-")

    # Ищем референсный диапазон в конце строки
    # Формат: числоA - числоB  или  числоA-числоB  (в конце строки)
    ref_pattern = r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$"
    ref_match = re.search(ref_pattern, rest)

    if not ref_match:
        # Попробуем формат <=N или >=N
        comp_pattern = r"(<=|>=|<|>)\s*(\d+(?:\.\d+)?)\s*$"
        comp_match = re.search(comp_pattern, rest)
        if comp_match:
            ref_text = f"{comp_match.group(1)}{comp_match.group(2)}"
            before = rest[:comp_match.start()].strip()
        else:
            return None, "", ""
    else:
        ref_text = f"{ref_match.group(1)}-{ref_match.group(2)}"
        before = rest[:ref_match.start()].strip()

    # Теперь из `before` извлекаем value и unit
    # before может быть: "8.23 *10^9/л" или "28 мм/ч" или "120 г/л"
    if not before:
        return None, "", ref_text

    # Сначала ищем число в начале
    val_match = re.match(r"^([-+]?\d+(?:[.,]\d+)?)\s*(.*)", before)
    if not val_match:
        return None, "", ref_text

    value = parse_float(val_match.group(1))
    unit = val_match.group(2).strip()

    return value, unit, ref_text


def fallback_parse_line(line: str) -> Optional[Tuple[str, float, str, str, str]]:
    """
    Пытается распарсить одну строку текста OCR.

    Возвращает (name, value, unit, ref_text) или None.
    Фильтр: строка должна содержать референсный диапазон.
    """
    s = re.sub(r"\s+", " ", (line or "").strip())
    if not s:
        return None

    # Строка должна содержать хотя бы один диапазон (число-число)
    if not re.search(r"\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?", s):
        # Или формат <=/>= (более редкий)
        if not re.search(r"(<=|>=|<|>)\s*\d+", s):
            # Или формат «до число»
            if not re.search(r"[Дд]о\s*\d+", s):
                return None

    # Ищем первое число в строке — это начало данных (после имени)
    num_match = re.search(r"(?<![A-Za-zА-Яа-я\-])([-+]?\d+(?:[.,]\d+)?)\s", s)
    if not num_match:
        return None

    name_part = s[:num_match.start()].strip()
    rest_part = s[num_match.start():].strip()

    if not name_part or not re.search(r"[A-Za-zА-Яа-я]{2,}", name_part):
        return None

    value, unit, ref_text = split_value_unit_ref(rest_part)
    if value is None or not ref_text:
        return None

    return name_part, value, unit, ref_text


def fallback_parse_candidates(raw_text: str) -> List[Item]:
    """
    Fallback-парсер: обрабатывает текст OCR и возвращает список Item.
    Применяет split_value_unit_ref к каждой строке-кандидату.
    """
    items: List[Item] = []

    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line:
            continue

        # Если есть табуляции — пробуем стандартный формат (name\tvalue\tref\tunit)
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
            if len(parts) >= 3:
                raw_name = parts[0]
                raw_val = parts[1]
                ref_text = parts[2]
                unit = parts[3] if len(parts) >= 4 else ""

                raw_name_cleaned = clean_raw_name(raw_name)
                name = normalize_name(raw_name)
                if name == raw_name.replace(" ", "_").replace("-", "_").upper():
                    name = normalize_name(raw_name_cleaned)

                value = parse_float(raw_val)
                ref = parse_ref_range(ref_text) if ref_text else None
                status = status_by_range(value, ref)
                ref_source = "референс лаборатории" if ref else "нет"

                items.append(Item(
                    raw_name=raw_name,
                    name=name,
                    value=value,
                    unit=unit,
                    ref_text=ref_text,
                    ref=ref,
                    ref_source=ref_source,
                    status=status,
                ))
                continue

        # Без табуляций — пробуем универсальный парсинг
        result = fallback_parse_line(line)
        if result is None:
            continue

        raw_name, value, unit, ref_text = result

        raw_name_cleaned = clean_raw_name(raw_name)
        name = normalize_name(raw_name)
        if name == raw_name.replace(" ", "_").replace("-", "_").upper():
            name = normalize_name(raw_name_cleaned)

        ref = parse_ref_range(ref_text) if ref_text else None
        status = status_by_range(value, ref)
        ref_source = "референс лаборатории" if ref else "нет"

        items.append(Item(
            raw_name=raw_name,
            name=name,
            value=value,
            unit=unit,
            ref_text=ref_text,
            ref=ref,
            ref_source=ref_source,
            status=status,
        ))

    return items




