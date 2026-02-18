"""
Тесты для reason-codes в quality-метриках.

Проверяем:
  - filtered_header_count и duplicate_dropped_count присутствуют в результате
  - Значения корректно пробрасываются
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import Item, Range
from parsers.quality import evaluate_parse_quality


def _make_item(
    name: str,
    value: float = 0.0,
    confidence: float = 0.0,
    ref: "Range | None" = None,
    unit: str = "",
    status: str = "В НОРМЕ",
    raw_name: str = "",
) -> Item:
    """Хелпер для создания Item с минимальными параметрами."""
    return Item(
        raw_name=raw_name or name,
        name=name,
        value=value,
        unit=unit,
        ref_text="",
        ref=ref,
        ref_source="",
        status=status,
        confidence=confidence,
    )


class TestQualityReasonCodes:
    """Проверяем reason-codes в quality-метриках."""

    def test_filtered_header_count_present(self):
        items = [_make_item("WBC", value=8.23, confidence=1.0, ref=Range(4, 10), unit="*10^9/л")]
        quality = evaluate_parse_quality(items)
        assert "filtered_header_count" in quality

    def test_duplicate_dropped_count_present(self):
        items = [_make_item("WBC", value=8.23, confidence=1.0, ref=Range(4, 10), unit="*10^9/л")]
        quality = evaluate_parse_quality(items)
        assert "duplicate_dropped_count" in quality

    def test_default_values_zero(self):
        """По умолчанию reason-codes равны 0."""
        items = [_make_item("WBC", value=8.23, confidence=1.0)]
        quality = evaluate_parse_quality(items)
        assert quality["filtered_header_count"] == 0
        assert quality["duplicate_dropped_count"] == 0

    def test_filtered_header_count_passed(self):
        """Переданное значение filtered_header_count сохраняется."""
        items = [_make_item("WBC", value=8.23, confidence=1.0)]
        quality = evaluate_parse_quality(items, filtered_header_count=5)
        assert quality["filtered_header_count"] == 5

    def test_dedup_dropped_count_passed(self):
        """Переданное значение dedup_dropped_count сохраняется."""
        items = [_make_item("WBC", value=8.23, confidence=1.0)]
        quality = evaluate_parse_quality(items, dedup_dropped_count=3)
        assert quality["duplicate_dropped_count"] == 3

    def test_both_reason_codes_passed(self):
        """Оба reason-codes передаются одновременно."""
        items = [
            _make_item("WBC", value=8.23, confidence=1.0),
            _make_item("RBC", value=4.5, confidence=1.0),
        ]
        quality = evaluate_parse_quality(
            items, filtered_header_count=2, dedup_dropped_count=1,
        )
        assert quality["filtered_header_count"] == 2
        assert quality["duplicate_dropped_count"] == 1

    def test_duplicate_dropped_matches_actual(self):
        """Если 3 WBC → dropped = 2 (пробрасывается из deduplicate_items)."""
        from engine import deduplicate_items
        items = [
            _make_item("WBC", value=8.23, confidence=1.0, ref=Range(4, 10), unit="*10^9/л"),
            _make_item("WBC", value=8.0, confidence=0.5, ref=None, unit=""),
            _make_item("WBC", value=8.1, confidence=0.7, ref=Range(4, 10), unit=""),
        ]
        deduped, dropped = deduplicate_items(items)
        quality = evaluate_parse_quality(deduped, dedup_dropped_count=dropped)
        assert quality["duplicate_dropped_count"] == 2
        assert len(deduped) == 1


