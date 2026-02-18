"""
Тесты для дедупликации items по canonical name.

Проверяем:
  - deduplicate_items() корректно выбирает лучший из дублей
  - Показатели с разными canonical name не дедуплицируются
  - После дедупликации high_low формируется корректно
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import Item, Range, deduplicate_items


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


class TestDeduplicateItems:
    """Дедупликация items по canonical name."""

    def test_no_duplicates_unchanged(self):
        """Если дублей нет — items без изменений."""
        items = [
            _make_item("WBC", value=8.23, confidence=1.0),
            _make_item("RBC", value=4.5, confidence=1.0),
        ]
        result, dropped = deduplicate_items(items)
        assert len(result) == 2
        assert dropped == 0

    def test_duplicate_keeps_higher_confidence(self):
        """Из двух WBC — выбираем с бóльшим confidence."""
        it1 = _make_item("WBC", value=8.23, confidence=0.7, ref=None, unit="")
        it2 = _make_item("WBC", value=8.23, confidence=1.0, ref=Range(4, 10), unit="*10^9/л")
        result, dropped = deduplicate_items([it1, it2])
        assert len(result) == 1
        assert dropped == 1
        assert result[0].confidence == 1.0

    def test_duplicate_prefers_with_ref(self):
        """При равном confidence — выбираем с ref."""
        it1 = _make_item("HGB", value=145, confidence=0.7, ref=None, unit="г/л")
        it2 = _make_item("HGB", value=145, confidence=0.7, ref=Range(130, 160), unit="г/л")
        result, dropped = deduplicate_items([it1, it2])
        assert len(result) == 1
        assert dropped == 1
        assert result[0].ref is not None

    def test_duplicate_prefers_with_unit(self):
        """При равном confidence и ref — выбираем с unit."""
        it1 = _make_item("PLT", value=250, confidence=0.7, ref=Range(150, 400), unit="")
        it2 = _make_item("PLT", value=250, confidence=0.7, ref=Range(150, 400), unit="*10^9/л")
        result, dropped = deduplicate_items([it1, it2])
        assert len(result) == 1
        assert dropped == 1
        assert result[0].unit == "*10^9/л"

    def test_three_duplicates_one_survives(self):
        """Три WBC — остаётся один лучший."""
        items = [
            _make_item("WBC", value=8.23, confidence=0.5, ref=None, unit=""),
            _make_item("WBC", value=8.23, confidence=1.0, ref=Range(4, 10), unit="*10^9/л"),
            _make_item("WBC", value=8.0, confidence=0.7, ref=Range(4, 10), unit=""),
        ]
        result, dropped = deduplicate_items(items)
        assert len(result) == 1
        assert dropped == 2
        assert result[0].confidence == 1.0

    def test_different_names_not_deduped(self):
        """WBC и RBC — не дедуплицируются."""
        items = [
            _make_item("WBC", value=8.23, confidence=1.0),
            _make_item("RBC", value=4.5, confidence=1.0),
        ]
        result, dropped = deduplicate_items(items)
        assert len(result) == 2
        assert dropped == 0

    def test_dedup_does_not_affect_high_low(self):
        """После дедупликации high_low формируется корректно."""
        items = [
            _make_item("ESR", value=28, confidence=1.0, ref=Range(2, 20), status="ВЫШЕ"),
            _make_item("ESR", value=28, confidence=0.5, ref=None, status="ВЫШЕ"),
        ]
        deduped, dropped = deduplicate_items(items)
        high_low = [
            it for it in deduped
            if it.confidence >= 0.7 and it.status in ("ВЫШЕ", "НИЖЕ")
        ]
        assert len(high_low) == 1
        assert high_low[0].confidence == 1.0
        assert dropped == 1

    def test_empty_items(self):
        """Пустой список items — пустой результат."""
        result, dropped = deduplicate_items([])
        assert len(result) == 0
        assert dropped == 0

    def test_single_item(self):
        """Один item — без изменений."""
        items = [_make_item("WBC", value=8.23, confidence=1.0)]
        result, dropped = deduplicate_items(items)
        assert len(result) == 1
        assert dropped == 0

    def test_dropped_count_correct(self):
        """Проверяем, что dropped_count считается правильно."""
        items = [
            _make_item("WBC", value=8.23, confidence=1.0),
            _make_item("WBC", value=8.0, confidence=0.5),
            _make_item("RBC", value=4.5, confidence=1.0),
            _make_item("RBC", value=4.3, confidence=0.7),
            _make_item("HGB", value=145, confidence=1.0),
        ]
        result, dropped = deduplicate_items(items)
        assert len(result) == 3  # WBC, RBC, HGB
        assert dropped == 2  # 1 WBC + 1 RBC

    def test_duplicate_different_raw_name_same_canonical(self):
        """Разные raw_name но одинаковый canonical → дедуплицируются."""
        it1 = _make_item("WBC", value=8.23, confidence=0.7, raw_name="Лейкоциты (WBC)")
        it2 = _make_item("WBC", value=8.23, confidence=1.0, raw_name="Лейкоциты WBC")
        result, dropped = deduplicate_items([it1, it2])
        assert len(result) == 1
        assert dropped == 1
        assert result[0].confidence == 1.0


