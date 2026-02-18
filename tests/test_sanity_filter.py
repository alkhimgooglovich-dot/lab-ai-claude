"""
Тесты Этапа 4.2: Sanity Outlier Filter.

Проверяем:
  1. Явные OCR-мусорные значения отбрасываются для известных показателей.
  2. Граничные нормальные значения НЕ отбрасываются.
  3. Для неизвестных canonical — фильтр не применяется.
  4. reason-code sanity_outlier_count присутствует в quality.
  5. Регрессия: golden-кейсы не ломаются.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parsers.sanity_ranges import is_sanity_outlier, SANITY_RANGES
from engine import Item, Range, apply_sanity_filter, assign_confidence
from parsers.quality import evaluate_parse_quality


def _make_item(name, value, confidence=0.8, ref=None, unit=""):
    return Item(
        raw_name=name, name=name, value=value, unit=unit,
        ref_text="", ref=ref, ref_source="", status="В НОРМЕ",
        confidence=confidence,
    )


# ─── Блок 1: is_sanity_outlier ───────────────────────────────

class TestIsSanityOutlier:

    def test_wbc_normal(self):
        assert is_sanity_outlier("WBC", 8.5) is False

    def test_wbc_ocr_garbage(self):
        """8500 вместо 8.5 — типичный OCR-мусор"""
        assert is_sanity_outlier("WBC", 8500.0) is True

    def test_wbc_extreme_but_real(self):
        """WBC=150 — гиперлейкоцитоз при лейкозе, реально бывает"""
        assert is_sanity_outlier("WBC", 150.0) is False

    def test_hgb_normal(self):
        assert is_sanity_outlier("HGB", 120.0) is False

    def test_hgb_ocr_garbage(self):
        """12000 вместо 120 — мусор"""
        assert is_sanity_outlier("HGB", 12000.0) is True

    def test_hgb_too_low(self):
        """1.0 — физически невозможно, мусор"""
        assert is_sanity_outlier("HGB", 1.0) is True

    def test_plt_normal(self):
        assert is_sanity_outlier("PLT", 220.0) is False

    def test_plt_ocr_garbage(self):
        assert is_sanity_outlier("PLT", 220000.0) is True

    def test_glu_normal(self):
        assert is_sanity_outlier("GLU", 5.4) is False

    def test_glu_ocr_garbage(self):
        assert is_sanity_outlier("GLU", 540.0) is True

    def test_crea_normal(self):
        assert is_sanity_outlier("CREA", 90.0) is False

    def test_crea_severe_ckd(self):
        """CREA=1500 — тяжёлая ХПН, реально бывает"""
        assert is_sanity_outlier("CREA", 1500.0) is False

    def test_unknown_canonical(self):
        """Для неизвестного показателя фильтр НЕ применяется"""
        assert is_sanity_outlier("UNKNOWN_MARKER", 99999.0) is False
        assert is_sanity_outlier("VITB12", 5000.0) is False

    def test_all_known_canonicals_in_dict(self):
        """Словарь содержит все требуемые показатели"""
        required = {"WBC", "RBC", "HGB", "HCT", "PLT", "ALT", "AST", "GLU", "CRP", "CREA"}
        assert required.issubset(set(SANITY_RANGES.keys()))


# ─── Блок 2: apply_sanity_filter ─────────────────────────────

class TestApplySanityFilter:

    def test_garbage_wbc_removed(self):
        items = [
            _make_item("WBC", 8500.0),   # мусор
            _make_item("RBC", 4.5),      # норма
        ]
        filtered, count = apply_sanity_filter(items)
        names = [it.name for it in filtered]
        assert "WBC" not in names
        assert "RBC" in names
        assert count == 1

    def test_normal_values_kept(self):
        items = [
            _make_item("WBC", 8.5),
            _make_item("HGB", 130.0),
            _make_item("PLT", 220.0),
        ]
        filtered, count = apply_sanity_filter(items)
        assert len(filtered) == 3
        assert count == 0

    def test_unknown_canonical_kept(self):
        """Неизвестный показатель с любым значением не удаляется"""
        items = [
            _make_item("SOMEMARKER", 99999.0),
        ]
        filtered, count = apply_sanity_filter(items)
        assert len(filtered) == 1
        assert count == 0

    def test_none_value_kept(self):
        """Item без значения (value=None) не трогаем"""
        items = [_make_item("WBC", None)]
        filtered, count = apply_sanity_filter(items)
        assert len(filtered) == 1
        assert count == 0

    def test_multiple_garbage_counted(self):
        items = [
            _make_item("WBC", 9999.0),
            _make_item("HGB", 99999.0),
            _make_item("GLU", 5.5),      # норма
        ]
        filtered, count = apply_sanity_filter(items)
        assert count == 2
        assert len(filtered) == 1


# ─── Блок 3: reason-code в quality ───────────────────────────

class TestSanityOutlierReasonCode:

    def test_sanity_outlier_count_present(self):
        items = [_make_item("WBC", 8.5, confidence=1.0, ref=Range(4, 10), unit="*10^9/л")]
        quality = evaluate_parse_quality(items)
        assert "sanity_outlier_count" in quality

    def test_sanity_outlier_count_default_zero(self):
        items = [_make_item("WBC", 8.5, confidence=1.0)]
        quality = evaluate_parse_quality(items)
        assert quality["sanity_outlier_count"] == 0

    def test_sanity_outlier_count_passed(self):
        items = [_make_item("WBC", 8.5, confidence=1.0)]
        quality = evaluate_parse_quality(items, sanity_outlier_count=3)
        assert quality["sanity_outlier_count"] == 3


# ─── Блок 4: регрессия — golden-кейс не ломается ─────────────

class TestSanityFilterRegression:
    """Sanity-фильтр не должен убирать нормальные значения из golden-кейсов."""

    GOLDEN_CBC = [
        ("WBC",  8.23),
        ("RBC",  4.0),
        ("HGB",  120.0),
        ("HCT",  34.7),
        ("PLT",  199.0),
    ]

    def test_golden_cbc_survives_filter(self):
        items = [_make_item(name, val) for name, val in self.GOLDEN_CBC]
        filtered, count = apply_sanity_filter(items)
        assert count == 0, f"Sanity-фильтр убрал нормальные значения: count={count}"
        assert len(filtered) == len(self.GOLDEN_CBC)

    def test_boundary_crea_survives(self):
        """CREA=62 (нижняя граница в golden-11) не отбрасывается"""
        items = [_make_item("CREA", 62.0)]
        filtered, count = apply_sanity_filter(items)
        assert count == 0
        assert len(filtered) == 1

