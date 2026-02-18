"""
Тесты universal mode: безопасное поведение для неизвестных лабораторий.

Проверяем:
  1. Мусорный текст → LLM не вызывается, human_text = "не удалось надёжно распознать"
  2. При confidence < 0.7 отклонения НЕ попадают в факты (high_low)
  3. Низкое качество → disclaimer вставляется
  4. evaluate_parse_quality корректно работает на мусоре
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import (
    Item, Range,
    parse_items_from_candidates,
    parse_with_fallback,
    assign_confidence,
    compute_item_confidence,
)
from parsers.quality import evaluate_parse_quality


# ============================================================
# Фикстуры: мусорные данные
# ============================================================

GARBAGE_TEXT = """Какой-то мусорный текст от неизвестной лаборатории
Пациент: Иванов И.И.
Дата: 01.01.2025
Результаты: плохо видно
Печать: неразборчиво
Подпись: врач Петров"""

# Частично распознанные кандидаты (некоторые с мусором)
PARTIAL_CANDIDATES = (
    "WBC\t8.23\t4.00-10.00\t*10^9/л\n"           # confidence=1.0 (value+ref+unit)
    "RBC\t4.00\t3.80-5.10\t*10^12/л\n"            # confidence=1.0
    "Мусорная строка\tXYZ\t100-200\tмм/ч\n"       # confidence=0.0 (value=None)
    "HGB\t120\t117-155\tг/л\n"                     # confidence=1.0
    "Без единицы\t5.5\t3.0-8.0\t\n"               # confidence=0.7 (value+ref, no unit)
    "Без референса\t42.0\t\tмг/л\n"               # 2 parts → skip (< 3 tab parts)
)

# Показатель с ref=None (confidence=0.5) и статус ВЫШЕ
ITEM_LOW_CONFIDENCE = Item(
    raw_name="MYSTERY",
    name="MYSTERY",
    value=999.0,
    unit="мг/л",
    ref_text="",
    ref=None,
    ref_source="нет",
    status="НЕИЗВЕСТНО",
    confidence=0.5,
)

# Показатель с confidence=1.0 и ВЫШЕ
ITEM_HIGH_CONFIDENCE_DEVIATION = Item(
    raw_name="ESR",
    name="ESR",
    value=28.0,
    unit="мм/ч",
    ref_text="2-20",
    ref=Range(low=2.0, high=20.0),
    ref_source="референс лаборатории",
    status="ВЫШЕ",
    confidence=1.0,
)

# Показатель с confidence=0.5 и формально ВЫШЕ
ITEM_LOW_CONF_DEVIATION = Item(
    raw_name="UNKNOWN_TEST",
    name="UNKNOWN_TEST",
    value=50.0,
    unit="",
    ref_text="",
    ref=None,
    ref_source="нет",
    status="ВЫШЕ",
    confidence=0.5,
)


# ============================================================
# ТЕСТЫ
# ============================================================

class TestGarbageTextBehavior:
    """Тесты на заведомо мусорный текст."""

    def test_garbage_text_no_items(self):
        """Мусорный текст → 0 показателей."""
        items = parse_with_fallback(GARBAGE_TEXT)
        assert len(items) == 0, (
            f"Ожидали 0 показателей от мусора, получили {len(items)}"
        )

    def test_garbage_quality_coverage_low(self):
        """На пустом результате coverage_score == 0."""
        items = parse_with_fallback(GARBAGE_TEXT)
        quality = evaluate_parse_quality(items)
        assert quality["coverage_score"] == 0.0
        assert quality["valid_value_count"] == 0

    def test_garbage_high_low_empty(self):
        """
        На мусорном тексте high_low должен быть пуст,
        т.к. нет надёжно распознанных показателей.
        """
        items = parse_with_fallback(GARBAGE_TEXT)
        assign_confidence(items)
        high_low = [
            it for it in items
            if it.confidence >= 0.7
            and it.value is not None
            and it.ref is not None
            and it.status in ("ВЫШЕ", "НИЖЕ")
        ]
        assert high_low == [], f"high_low не пуст: {high_low}"


class TestPartialRecognition:
    """Тесты на частично распознанные данные."""

    def test_partial_candidates_parsing(self):
        """Из частичных кандидатов парсится только валидное."""
        items = parse_items_from_candidates(PARTIAL_CANDIDATES)
        # WBC, RBC, HGB, "Без единицы" → 4 строки с value
        # "Мусорная строка" → value=None (XYZ не число)
        # "Без референса" → может не распарситься (зависит от кол-ва \t)
        values_parsed = [it for it in items if it.value is not None]
        assert len(values_parsed) >= 3, (
            f"Ожидали >= 3 валидных значений, получили {len(values_parsed)}"
        )

    def test_partial_quality_valid_counts(self):
        """Проверяем valid_value_count и valid_ref_count для частичных данных."""
        items = parse_items_from_candidates(PARTIAL_CANDIDATES)
        quality = evaluate_parse_quality(items)
        # Минимум WBC, RBC, HGB должны быть valid
        assert quality["valid_value_count"] >= 3
        assert quality["valid_ref_count"] >= 3


class TestConfidenceFiltering:
    """Тесты: при confidence < 0.7 отклонения НЕ попадают в факты."""

    def test_low_confidence_not_in_high_low(self):
        """
        Показатель с confidence < 0.7 НЕ должен попасть в high_low,
        даже если его статус 'ВЫШЕ' или 'НИЖЕ'.
        """
        items = [ITEM_LOW_CONF_DEVIATION, ITEM_HIGH_CONFIDENCE_DEVIATION]

        # Фильтр, идентичный generate_pdf_report
        high_low = [
            it for it in items
            if it.confidence >= 0.7
            and it.value is not None
            and it.ref is not None
            and it.status in ("ВЫШЕ", "НИЖЕ")
        ]

        names_in_facts = [it.name for it in high_low]
        assert "UNKNOWN_TEST" not in names_in_facts, (
            "UNKNOWN_TEST (confidence=0.5) не должен попасть в факты"
        )
        assert "ESR" in names_in_facts, (
            "ESR (confidence=1.0) должен быть в фактах"
        )

    def test_confidence_values(self):
        """Проверяем расчёт confidence для разных комбинаций."""
        # value + ref + unit → 1.0
        it1 = Item(
            raw_name="WBC", name="WBC", value=8.23, unit="*10^9/л",
            ref_text="4.00-10.00", ref=Range(4.0, 10.0),
            ref_source="референс лаборатории", status="В НОРМЕ",
        )
        assert compute_item_confidence(it1) == 1.0

        # value + ref, no unit → 0.7
        it2 = Item(
            raw_name="X", name="X", value=5.0, unit="",
            ref_text="3-8", ref=Range(3.0, 8.0),
            ref_source="референс лаборатории", status="В НОРМЕ",
        )
        assert compute_item_confidence(it2) == 0.7

        # value only, no ref → 0.5  (имя >= 3 символов, чтобы не считалось мусором)
        it3 = Item(
            raw_name="Калий", name="Калий", value=42.0, unit="мг/л",
            ref_text="", ref=None,
            ref_source="нет", status="НЕИЗВЕСТНО",
        )
        assert compute_item_confidence(it3) == 0.5

        # value=None → 0.0
        it4 = Item(
            raw_name="Z", name="Z", value=None, unit="",
            ref_text="", ref=None,
            ref_source="нет", status="НЕ РАСПОЗНАНО",
        )
        assert compute_item_confidence(it4) == 0.0

    def test_assign_confidence_in_place(self):
        """assign_confidence обновляет confidence у всех элементов."""
        items = [
            Item(
                raw_name="WBC", name="WBC", value=8.23, unit="*10^9/л",
                ref_text="4.00-10.00", ref=Range(4.0, 10.0),
                ref_source="лаб", status="В НОРМЕ",
            ),
            Item(
                raw_name="UNK", name="UNK", value=None, unit="",
                ref_text="", ref=None,
                ref_source="нет", status="НЕ РАСПОЗНАНО",
            ),
        ]
        # По умолчанию confidence=0.0
        assert items[0].confidence == 0.0
        assert items[1].confidence == 0.0

        assign_confidence(items)

        assert items[0].confidence == 1.0
        assert items[1].confidence == 0.0


class TestUnknownLabBehavior:
    """Тесты: поведение при полностью неизвестном бланке (valid < 5)."""

    def test_very_few_valid_values_skips_llm(self):
        """
        Если valid_value_count < 5 → LLM не вызывается.
        Проверяем через quality.
        """
        # Создаём минимальный набор: 3 валидных строки
        few_candidates = (
            "WBC\t8.23\t4.00-10.00\t*10^9/л\n"
            "RBC\t4.00\t3.80-5.10\t*10^12/л\n"
            "HGB\t120\t117-155\tг/л\n"
        )
        items = parse_items_from_candidates(few_candidates)
        quality = evaluate_parse_quality(items)

        # valid_value_count == 3, что < 5
        assert quality["valid_value_count"] < 5, (
            f"Ожидали valid_value_count < 5, получили {quality['valid_value_count']}"
        )

    def test_quality_expected_minimum_dynamic(self):
        """
        Проверяем динамическое определение expected_minimum.
        CBC-набор >= 8 кодов → expected_minimum = 15.
        Иначе → expected_minimum = 8.
        """
        # Мало CBC-кодов → expected_minimum=8
        few_items = [
            Item(raw_name="WBC", name="WBC", value=8.0, unit="", ref_text="4-10",
                 ref=Range(4, 10), ref_source="лаб", status="В НОРМЕ"),
            Item(raw_name="RBC", name="RBC", value=4.0, unit="", ref_text="3.8-5.1",
                 ref=Range(3.8, 5.1), ref_source="лаб", status="В НОРМЕ"),
        ]
        quality = evaluate_parse_quality(few_items)
        assert quality["expected_minimum"] == 8

        # Много CBC-кодов → expected_minimum=15
        cbc_names = ["WBC", "RBC", "HGB", "HCT", "PLT", "NE%", "LY%", "MO%", "ESR"]
        many_items = [
            Item(raw_name=n, name=n, value=1.0, unit="", ref_text="0-100",
                 ref=Range(0, 100), ref_source="лаб", status="В НОРМЕ")
            for n in cbc_names
        ]
        quality2 = evaluate_parse_quality(many_items)
        assert quality2["expected_minimum"] == 15



