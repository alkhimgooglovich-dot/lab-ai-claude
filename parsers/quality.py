"""
Модуль оценки качества парсинга (universal mode).

evaluate_parse_quality(items) -> dict с метриками:
  - valid_value_count: value != None и value выглядит как одно число
  - valid_ref_count:   ref распознан (low/high или comparator)
  - error_count:       value is None
  - suspicious_count:  value содержит пробелы / '^' '*' '/' / ref+value склейка
  - coverage_score:    valid_value_count / expected_minimum
  - expected_minimum:  динамически: 15 (если >=8 CBC-кодов) иначе 8
  - ref_coverage_ratio:  valid_ref_count / valid_value_count (доля с ref)
  - unit_coverage_ratio: valid_unit_count / valid_value_count (доля с unit)
  - duplicate_name_count: кол-во дублей по имени
  - avg_confidence:       средний confidence (если поле задано)
"""

import re
from typing import List, Set, TYPE_CHECKING
from collections import Counter

if TYPE_CHECKING:
    from engine import Item


# CBC-коды для динамического определения expected_minimum
CBC_CODES: Set[str] = {
    "WBC", "RBC", "HGB", "HCT", "PLT",
    "NE", "NE%", "LY", "LY%", "MO", "MO%",
    "EO", "EO%", "BA", "BA%", "ESR",
    "NE_SEG", "NE_STAB",
    "MCV", "MCH", "MCHC", "RDW-SD", "RDW-CV",
    "PDW", "MPV", "P-LCR",
}

CBC_THRESHOLD = 8        # сколько CBC-кодов нужно, чтобы считать панель CBC
CBC_EXPECTED_MIN = 15     # ожидаемый минимум для CBC
GENERIC_EXPECTED_MIN = 8  # ожидаемый минимум для любого набора


def _detect_expected_minimum(items: List["Item"]) -> int:
    """
    Динамически определяет expected_minimum:
      - если найдено >= CBC_THRESHOLD CBC-кодов → 15
      - иначе → 8
    """
    found_cbc = sum(1 for it in items if it.name in CBC_CODES)
    return CBC_EXPECTED_MIN if found_cbc >= CBC_THRESHOLD else GENERIC_EXPECTED_MIN


def _is_suspicious_item(it: "Item") -> bool:
    """
    Проверяет, является ли значение показателя подозрительным:
      - raw_name содержит '^' '*' '/' (кроме *10^N)
      - ref_text невалидный (слишком длинный, склейки)
    """
    # Проверка raw_name на мусор
    raw = it.raw_name or ""
    if any(ch in raw for ch in ['^', '*', '/']):
        if not re.search(r"\*10\^\d+", raw):
            return True

    ref_str = it.ref_text or ""
    val_str = f"{it.value:g}" if it.value is not None else ""

    # ref+value склейка: "150-400213"
    if ref_str and val_str:
        combined = ref_str.replace("-", "").replace(".", "")
        if len(combined) > 10 and not re.match(
            r"^\d{1,5}(\.\d+)?-\d{1,5}(\.\d+)?$",
            ref_str.replace(" ", ""),
        ):
            return True

    # ref_text с кучей частей (>3 частей через пробел — мусор)
    if ref_str and " " in ref_str.strip():
        parts = ref_str.strip().split()
        if len(parts) > 3:
            return True

    return False


def evaluate_parse_quality(
    items: List["Item"],
    expected_minimum: int | None = None,
    *,
    filtered_header_count: int | None = None,
    dedup_dropped_count: int | None = None,
    sanity_outlier_count: int | None = None,
) -> dict:
    """
    Оценивает качество результатов парсинга.

    Args:
        items: список Item из baseline-парсера (или fallback).
        expected_minimum: если передан — используем, иначе определяем динамически.

    Returns:
        dict с ключами:
            valid_value_count    — показатели, у которых value != None и не suspicious
            valid_ref_count      — показатели с распознанным ref (ref is not None)
            error_count          — показатели без значения (value is None)
            suspicious_count     — показатели с подозрительными данными
            coverage_score       — valid_value_count / expected_minimum (0..1+)
            expected_minimum     — порог, использованный для расчёта
            ref_coverage_ratio   — valid_ref_count / valid_value_count (0..1)
            unit_coverage_ratio  — valid_unit_count / valid_value_count (0..1)
            duplicate_name_count — кол-во имён, встречающихся >1 раза
            avg_confidence       — средний confidence по валидным item
    """
    if expected_minimum is None:
        expected_minimum = _detect_expected_minimum(items)

    valid_value_count = 0
    valid_ref_count = 0
    valid_unit_count = 0
    error_count = 0
    suspicious_count = 0
    confidence_sum = 0.0
    confidence_n = 0

    for it in items:
        # --- value отсутствует ---
        if it.value is None:
            error_count += 1
            continue

        # --- suspicious ---
        if _is_suspicious_item(it):
            suspicious_count += 1
            continue

        # --- valid ---
        valid_value_count += 1
        if it.ref is not None:
            valid_ref_count += 1
        if (it.unit or "").strip():
            valid_unit_count += 1

        # confidence (может быть ещё не вычислен → 0.0 по умолчанию)
        conf = getattr(it, "confidence", 0.0)
        confidence_sum += conf
        confidence_n += 1

    coverage_score = valid_value_count / max(expected_minimum, 1)

    # Новые метрики
    ref_coverage_ratio = (
        valid_ref_count / valid_value_count if valid_value_count > 0 else 0.0
    )
    unit_coverage_ratio = (
        valid_unit_count / valid_value_count if valid_value_count > 0 else 0.0
    )
    avg_confidence = (
        confidence_sum / confidence_n if confidence_n > 0 else 0.0
    )

    # Подсчёт дублей по имени
    name_counts = Counter(it.name for it in items if it.value is not None)
    duplicate_name_count = sum(1 for cnt in name_counts.values() if cnt > 1)

    return {
        "valid_value_count": valid_value_count,
        "valid_ref_count": valid_ref_count,
        "error_count": error_count,
        "suspicious_count": suspicious_count,
        "coverage_score": round(coverage_score, 3),
        "expected_minimum": expected_minimum,
        "ref_coverage_ratio": round(ref_coverage_ratio, 3),
        "unit_coverage_ratio": round(unit_coverage_ratio, 3),
        "duplicate_name_count": duplicate_name_count,
        "avg_confidence": round(avg_confidence, 3),
        "filtered_header_count": filtered_header_count if filtered_header_count is not None else 0,
        "duplicate_dropped_count": dedup_dropped_count if dedup_dropped_count is not None else 0,
        "sanity_outlier_count": sanity_outlier_count if sanity_outlier_count is not None else 0,
    }
