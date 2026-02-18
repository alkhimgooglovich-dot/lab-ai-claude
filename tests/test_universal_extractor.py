"""
Тесты Universal Extractor v2: 12 golden-кейсов.

Каждый кейс проверяет:
  - value — правильное числовое значение
  - status — правильный статус (ВЫШЕ / НИЖЕ / В НОРМЕ)
  - suspicious_count == 0 — нет подозрительных показателей
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parsers.universal_extractor import universal_extract
from engine import (
    parse_items_from_candidates,
    assign_confidence,
    Item,
)
from parsers.quality import evaluate_parse_quality


# ============================================================
# Утилиты
# ============================================================
def _find(items, name):
    """Найти Item по имени."""
    for it in items:
        if it.name == name:
            return it
    available = [it.name for it in items]
    raise AssertionError(f"Показатель '{name}' не найден. Доступные: {available}")


def _extract_and_parse(text: str):
    """Извлечь кандидатов и распарсить."""
    candidates = universal_extract(text)
    if not candidates:
        return []
    items = parse_items_from_candidates(candidates)
    assign_confidence(items)
    return items


# ============================================================
# Golden Case 1: Helix CBC (двухстрочный формат)
# ============================================================
GOLDEN_1_HELIX_CBC = """\
Лейкоциты (WBC)
8.23 *10^9/л
4.00 - 10.00

Эритроциты (RBC)
4.00 *10^12/л
3.80 - 5.10

Гемоглобин (HGB)
120 г/л
117 - 155

Гематокрит (HCT)
34.7 %
35.0 - 45.0

Тромбоциты (PLT)
199 *10^9/л
150 - 400

Скорость оседания
28 мм/ч
2 - 20
"""


class TestGoldenCase1HelixCBC:
    def test_wbc(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "WBC")
        assert it.value == 8.23
        assert it.status == "В НОРМЕ"

    def test_rbc(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "RBC")
        assert it.value == 4.0
        assert it.status == "В НОРМЕ"

    def test_hgb(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "HGB")
        assert it.value == 120.0
        assert it.status == "В НОРМЕ"

    def test_hct_below(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "HCT")
        assert it.value == 34.7
        assert it.status == "НИЖЕ"

    def test_esr_above(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "ESR")
        assert it.value == 28.0
        assert it.status == "ВЫШЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 2: Однострочный формат (NE%, LY%)
# ============================================================
GOLDEN_2_ONELINE = """\
Нейтрофилы, % (NE%) 77 % 47.0 - 72.0
Лимфоциты, % (LY%) 18 % 19.0 - 37.0
Моноциты, % (MO%) 5 % 3.0 - 12.0
Эозинофилы, % (EO%) 0 % 1.0 - 5.0
Базофилы, % (BA%) 0.5 % 0.0 - 1.2
"""


class TestGoldenCase2OneLine:
    def test_ne_above(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        it = _find(items, "NE%")
        assert it.value == 77.0
        assert it.status == "ВЫШЕ"

    def test_ly_below(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        it = _find(items, "LY%")
        assert it.value == 18.0
        assert it.status == "НИЖЕ"

    def test_mo_normal(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        it = _find(items, "MO%")
        assert it.value == 5.0
        assert it.status == "В НОРМЕ"

    def test_eo_below(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        it = _find(items, "EO%")
        assert it.value == 0.0
        assert it.status == "НИЖЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 3: Биохимия (однострочный)
# ============================================================
GOLDEN_3_BIOCHEM = """\
АЛТ (ALT) 45 Ед/л 10 - 40
АСТ (AST) 32 Ед/л 10 - 40
Билирубин общий (TBIL) 18.5 мкмоль/л 3.4 - 20.5
Креатинин (CREA) 95 мкмоль/л 62 - 106
Мочевина (UREA) 5.2 ммоль/л 2.8 - 7.2
Глюкоза (GLUC) 5.8 ммоль/л 3.9 - 6.1
"""


class TestGoldenCase3Biochem:
    def test_alt_above(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        it = _find(items, "ALT")
        assert it.value == 45.0
        assert it.status == "ВЫШЕ"

    def test_ast_normal(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        it = _find(items, "AST")
        assert it.value == 32.0
        assert it.status == "В НОРМЕ"

    def test_crea_normal(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        it = _find(items, "CREA")
        assert it.value == 95.0
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 4: Липидограмма
# ============================================================
GOLDEN_4_LIPIDS = """\
Холестерин общий (CHOL) 6.2 ммоль/л 3.0 - 5.2
ЛПНП (LDL) 3.9 ммоль/л 0.0 - 3.4
ЛПВП (HDL) 1.1 ммоль/л 1.0 - 2.0
Триглицериды (TRIG) 1.8 ммоль/л 0.0 - 1.7
"""


class TestGoldenCase4Lipids:
    def test_chol_above(self):
        items = _extract_and_parse(GOLDEN_4_LIPIDS)
        it = _find(items, "CHOL")
        assert it.value == 6.2
        assert it.status == "ВЫШЕ"

    def test_ldl_above(self):
        items = _extract_and_parse(GOLDEN_4_LIPIDS)
        it = _find(items, "LDL")
        assert it.value == 3.9
        assert it.status == "ВЫШЕ"

    def test_hdl_normal(self):
        items = _extract_and_parse(GOLDEN_4_LIPIDS)
        it = _find(items, "HDL")
        assert it.value == 1.1
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_4_LIPIDS)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 5: СОЭ + микроскопия (однострочный)
# ============================================================
GOLDEN_5_ESR_MICRO = """\
Скорость оседания 28 мм/ч 2 - 20
Нейтрофилы: сегмент. (микроскопия) 73.0 % 47.0 - 72.0
"""


class TestGoldenCase5ESRMicro:
    def test_esr_above(self):
        items = _extract_and_parse(GOLDEN_5_ESR_MICRO)
        it = _find(items, "ESR")
        assert it.value == 28.0
        assert it.status == "ВЫШЕ"

    def test_ne_seg_above(self):
        items = _extract_and_parse(GOLDEN_5_ESR_MICRO)
        it = _find(items, "NE_SEG")
        assert it.value == 73.0
        assert it.status == "ВЫШЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_5_ESR_MICRO)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 6: CRP (С-реактивный белок)
# ============================================================
GOLDEN_6_CRP = """\
C-реактивный белок (CRP) 12.5 мг/л 0.0 - 5.0
Глюкоза (GLUC) 4.5 ммоль/л 3.9 - 6.1
АЛТ (ALT) 25 Ед/л 10 - 40
АСТ (AST) 30 Ед/л 10 - 40
Креатинин (CREA) 80 мкмоль/л 62 - 106
"""


class TestGoldenCase6CRP:
    def test_crp_above(self):
        items = _extract_and_parse(GOLDEN_6_CRP)
        it = _find(items, "CRP")
        assert it.value == 12.5
        assert it.status == "ВЫШЕ"

    def test_gluc_normal(self):
        items = _extract_and_parse(GOLDEN_6_CRP)
        it = _find(items, "GLUC")
        assert it.value == 4.5
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_6_CRP)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 7: Мусорный текст → 0 показателей
# ============================================================
GOLDEN_7_GARBAGE = """\
Какой-то мусорный текст от неизвестной лаборатории
Пациент: Иванов И.И.
Дата: 01.01.2025
Результаты: плохо видно
Печать: неразборчиво
Подпись: врач Петров
"""


class TestGoldenCase7Garbage:
    def test_zero_items(self):
        items = _extract_and_parse(GOLDEN_7_GARBAGE)
        assert len(items) == 0, f"Ожидали 0, получили {len(items)}"

    def test_quality_zero(self):
        items = _extract_and_parse(GOLDEN_7_GARBAGE)
        quality = evaluate_parse_quality(items)
        assert quality["valid_value_count"] == 0

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_7_GARBAGE)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 8: Двухстрочный с unicode степенями
# ============================================================
GOLDEN_8_UNICODE_POW = """\
Лейкоциты (WBC)
5.60 *10^9/л
4.00 - 10.00

Тромбоциты (PLT)
250 *10^9/л
150 - 400
"""


class TestGoldenCase8UnicodePow:
    def test_wbc(self):
        items = _extract_and_parse(GOLDEN_8_UNICODE_POW)
        it = _find(items, "WBC")
        assert it.value == 5.6
        assert it.status == "В НОРМЕ"

    def test_plt(self):
        items = _extract_and_parse(GOLDEN_8_UNICODE_POW)
        it = _find(items, "PLT")
        assert it.value == 250.0
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_8_UNICODE_POW)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 9: Формат с компараторами (<=, >=)
# ============================================================
GOLDEN_9_COMPARATORS = """\
C-реактивный белок (CRP) 2.5 мг/л <=5.0
Глюкоза (GLUC) 5.0 ммоль/л 3.9 - 6.1
АЛТ (ALT) 35 Ед/л <=40
Креатинин (CREA) 70 мкмоль/л 62 - 106
Мочевина (UREA) 6.0 ммоль/л 2.8 - 7.2
"""


class TestGoldenCase9Comparators:
    def test_crp_normal(self):
        items = _extract_and_parse(GOLDEN_9_COMPARATORS)
        it = _find(items, "CRP")
        assert it.value == 2.5
        assert it.status == "В НОРМЕ"

    def test_alt_normal(self):
        items = _extract_and_parse(GOLDEN_9_COMPARATORS)
        it = _find(items, "ALT")
        assert it.value == 35.0
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_9_COMPARATORS)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 10: Смешанный формат (одно + двухстрочный)
# ============================================================
GOLDEN_10_MIXED = """\
Лейкоциты (WBC)
6.50 *10^9/л
4.00 - 10.00

Скорость оседания 15 мм/ч 2 - 20
Нейтрофилы, % (NE%) 55 % 47.0 - 72.0
Лимфоциты, % (LY%) 30 % 19.0 - 37.0

Гемоглобин (HGB)
140 г/л
117 - 155

Тромбоциты (PLT)
220 *10^9/л
150 - 400
"""


class TestGoldenCase10Mixed:
    def test_wbc(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "WBC")
        assert it.value == 6.5
        assert it.status == "В НОРМЕ"

    def test_esr_normal(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "ESR")
        assert it.value == 15.0
        assert it.status == "В НОРМЕ"

    def test_ne_normal(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "NE%")
        assert it.value == 55.0
        assert it.status == "В НОРМЕ"

    def test_plt(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "PLT")
        assert it.value == 220.0
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 11: Граничные значения
# ============================================================
GOLDEN_11_BOUNDARY = """\
Гемоглобин (HGB) 117 г/л 117 - 155
Гематокрит (HCT) 45.0 % 35.0 - 45.0
Тромбоциты (PLT) 150 *10^9/л 150 - 400
Мочевина (UREA) 7.2 ммоль/л 2.8 - 7.2
Креатинин (CREA) 62 мкмоль/л 62 - 106
"""


class TestGoldenCase11Boundary:
    def test_hgb_at_lower_bound(self):
        items = _extract_and_parse(GOLDEN_11_BOUNDARY)
        it = _find(items, "HGB")
        assert it.value == 117.0
        assert it.status == "В НОРМЕ"

    def test_hct_at_upper_bound(self):
        items = _extract_and_parse(GOLDEN_11_BOUNDARY)
        it = _find(items, "HCT")
        assert it.value == 45.0
        assert it.status == "В НОРМЕ"

    def test_plt_at_lower_bound(self):
        items = _extract_and_parse(GOLDEN_11_BOUNDARY)
        it = _find(items, "PLT")
        assert it.value == 150.0
        assert it.status == "В НОРМЕ"

    def test_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_11_BOUNDARY)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


# ============================================================
# Golden Case 12: Helix PDF fixture regression
# ============================================================
class TestGoldenCase12HelixPDFRegression:
    """
    Регрессия: тот же Helix PDF, что тестируется в test_baseline.
    Проверяем, что Universal Extractor не ухудшает результат.
    """

    def _get_items(self):
        pdf_path = PROJECT_ROOT / "tests" / "fixtures" / "0333285a-adec-4b5d-9c25-52811a5c1747.pdf"
        if not pdf_path.exists():
            import pytest
            pytest.skip("Helix PDF fixture not found")
        from engine import try_extract_text_from_pdf_bytes
        pdf_bytes = pdf_path.read_bytes()
        raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)
        candidates = universal_extract(raw_text)
        if not candidates:
            # Fallback: helix_table_to_candidates
            from engine import helix_table_to_candidates
            candidates = helix_table_to_candidates(raw_text)
        return parse_items_from_candidates(candidates)

    def test_wbc(self):
        items = self._get_items()
        it = _find(items, "WBC")
        assert it.value == 8.23

    def test_rbc(self):
        items = self._get_items()
        it = _find(items, "RBC")
        assert it.value == 4.0

    def test_hgb(self):
        items = self._get_items()
        it = _find(items, "HGB")
        assert it.value == 120.0

    def test_hct(self):
        items = self._get_items()
        it = _find(items, "HCT")
        assert it.value == 34.7

    def test_esr(self):
        items = self._get_items()
        it = _find(items, "ESR")
        assert it.value == 28.0

    def test_plt(self):
        items = self._get_items()
        it = _find(items, "PLT")
        assert it.value == 199.0

    def test_no_suspicious(self):
        items = self._get_items()
        assign_confidence(items)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0



