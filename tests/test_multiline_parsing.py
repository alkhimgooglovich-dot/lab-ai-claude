"""
Тесты Multi-line Parsing для Universal Extractor v2.

Проверяем, что _multi_line_pass корректно собирает показатели,
разбитые на 2–4 строки (имя, значение, единица, референс — на разных строках).

10 кейсов + регрессия по golden cases.
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
# Кейс 1: Классический 3-строчный (name / value+unit / ref)
# ============================================================
CASE_3LINE_CLASSIC = """\
Лейкоциты (WBC)
8.23 *10^9/л
4.00 - 10.00
"""


class TestMultiLine3Lines:
    """3-строчные кейсы: name / value+unit / ref"""

    def test_wbc_value(self):
        items = _extract_and_parse(CASE_3LINE_CLASSIC)
        it = _find(items, "WBC")
        assert it.value == 8.23

    def test_wbc_ref(self):
        items = _extract_and_parse(CASE_3LINE_CLASSIC)
        it = _find(items, "WBC")
        assert it.ref is not None
        assert it.ref.low == 4.0
        assert it.ref.high == 10.0

    def test_wbc_unit(self):
        items = _extract_and_parse(CASE_3LINE_CLASSIC)
        it = _find(items, "WBC")
        assert "*10^9" in it.unit

    def test_wbc_status(self):
        items = _extract_and_parse(CASE_3LINE_CLASSIC)
        it = _find(items, "WBC")
        assert it.status == "В НОРМЕ"


# ============================================================
# Кейс 2: 4-строчный (name / value / unit / ref)
# ============================================================
CASE_4LINE_SPLIT = """\
Гемоглобин (HGB)
120
г/л
117 - 155
"""


class TestMultiLine4Lines:
    """4-строчные кейсы: name / value / unit / ref"""

    def test_hgb_value(self):
        items = _extract_and_parse(CASE_4LINE_SPLIT)
        it = _find(items, "HGB")
        assert it.value == 120.0

    def test_hgb_unit(self):
        items = _extract_and_parse(CASE_4LINE_SPLIT)
        it = _find(items, "HGB")
        assert "г/л" in it.unit

    def test_hgb_ref(self):
        items = _extract_and_parse(CASE_4LINE_SPLIT)
        it = _find(items, "HGB")
        assert it.ref is not None
        assert it.ref.low == 117.0
        assert it.ref.high == 155.0


# ============================================================
# Кейс 3: 3-строчный (name / value+unit / ref) — unit в value-строке
# ============================================================
CASE_3LINE_UNIT_IN_VALUE = """\
Тромбоциты (PLT)
199 *10^9/л
150 - 400
"""


class TestMultiLine3LinesUnitInValue:
    def test_plt_value(self):
        items = _extract_and_parse(CASE_3LINE_UNIT_IN_VALUE)
        it = _find(items, "PLT")
        assert it.value == 199.0

    def test_plt_ref(self):
        items = _extract_and_parse(CASE_3LINE_UNIT_IN_VALUE)
        it = _find(items, "PLT")
        assert it.ref is not None
        assert it.ref.low == 150.0
        assert it.ref.high == 400.0

    def test_plt_unit(self):
        items = _extract_and_parse(CASE_3LINE_UNIT_IN_VALUE)
        it = _find(items, "PLT")
        assert "*10^9" in it.unit


# ============================================================
# Кейс 4: 3-строчный с unit на отдельной строке ПОСЛЕ ref
# ============================================================
CASE_3LINE_UNIT_AFTER_REF = """\
Креатинин (CREA)
95
62 - 106
мкмоль/л
"""


class TestMultiLine3LinesUnitAfterRef:
    def test_crea_value(self):
        items = _extract_and_parse(CASE_3LINE_UNIT_AFTER_REF)
        it = _find(items, "CREA")
        assert it.value == 95.0

    def test_crea_ref(self):
        items = _extract_and_parse(CASE_3LINE_UNIT_AFTER_REF)
        it = _find(items, "CREA")
        assert it.ref is not None
        assert it.ref.low == 62.0
        assert it.ref.high == 106.0

    def test_crea_unit(self):
        items = _extract_and_parse(CASE_3LINE_UNIT_AFTER_REF)
        it = _find(items, "CREA")
        assert "мкмоль/л" in it.unit


# ============================================================
# Кейс 5: Табличный — unit и ref на соседних строках
# ============================================================
CASE_TABLE_SPLIT = """\
Глюкоза (GLUC)
5.8
ммоль/л
3.9 - 6.1

Холестерин (CHOL)
6.2
ммоль/л
3.0 - 5.2
"""


class TestMultiLineTable:
    """Табличные кейсы с несколькими показателями."""

    def test_gluc_parsed(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        it = _find(items, "GLUC")
        assert it.value == 5.8

    def test_chol_parsed(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        it = _find(items, "CHOL")
        assert it.value == 6.2

    def test_gluc_ref(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        it = _find(items, "GLUC")
        assert it.ref is not None
        assert it.ref.low == 3.9
        assert it.ref.high == 6.1

    def test_chol_ref(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        it = _find(items, "CHOL")
        assert it.ref is not None
        assert it.ref.low == 3.0
        assert it.ref.high == 5.2

    def test_gluc_unit(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        it = _find(items, "GLUC")
        assert "ммоль/л" in it.unit

    def test_chol_unit(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        it = _find(items, "CHOL")
        assert "ммоль/л" in it.unit

    def test_count_items(self):
        items = _extract_and_parse(CASE_TABLE_SPLIT)
        assert len(items) >= 2


# ============================================================
# Кейс 6: Смешанный — одни показатели в 1 строку, другие в 3
# ============================================================
CASE_MIXED = """\
АЛТ (ALT) 45 Ед/л 10 - 40
Билирубин (TBIL)
12.3
мкмоль/л
3.4 - 20.5
АСТ (AST) 32 Ед/л 10 - 40
"""


class TestMultiLineMixed:
    """Смешанные: one-line + multi-line в одном тексте."""

    def test_alt_oneline(self):
        items = _extract_and_parse(CASE_MIXED)
        it = _find(items, "ALT")
        assert it.value == 45.0

    def test_tbil_multiline(self):
        items = _extract_and_parse(CASE_MIXED)
        it = _find(items, "TBIL")
        assert it.value == 12.3

    def test_tbil_unit(self):
        items = _extract_and_parse(CASE_MIXED)
        it = _find(items, "TBIL")
        assert "мкмоль/л" in it.unit

    def test_tbil_ref(self):
        items = _extract_and_parse(CASE_MIXED)
        it = _find(items, "TBIL")
        assert it.ref is not None
        assert it.ref.low == 3.4
        assert it.ref.high == 20.5

    def test_ast_oneline(self):
        items = _extract_and_parse(CASE_MIXED)
        it = _find(items, "AST")
        assert it.value == 32.0


# ============================================================
# Кейс 7: Multi-line НЕ должен склеить чужие строки
# ============================================================
CASE_NO_FALSE_MERGE = """\
Лейкоциты (WBC)
8.23 *10^9/л
4.00 - 10.00

Эритроциты (RBC)
4.00 *10^12/л
3.80 - 5.10
"""


# ============================================================
# Кейс 8: Строка-имя без value в окне → НЕ формировать кандидата
# ============================================================
CASE_NAME_WITHOUT_VALUE = """\
Лейкоциты (WBC)
Примечание: пересдать анализ
Эритроциты (RBC)
4.00 *10^12/л
3.80 - 5.10
"""


# ============================================================
# Кейс 9: Со стрелками ↑↓ в value-строке
# ============================================================
CASE_ARROWS = """\
СОЭ (ESR)
↑ 28 мм/ч
2 - 20
"""


# ============================================================
# Кейс 10: Comparator ref на отдельной строке
# ============================================================
CASE_COMPARATOR_REF = """\
С-реактивный белок (CRP)
0.5
мг/л
<=5.0
"""


class TestMultiLineEdgeCases:
    """Граничные случаи."""

    def test_no_false_merge_wbc(self):
        items = _extract_and_parse(CASE_NO_FALSE_MERGE)
        it = _find(items, "WBC")
        assert it.value == 8.23

    def test_no_false_merge_rbc(self):
        items = _extract_and_parse(CASE_NO_FALSE_MERGE)
        it = _find(items, "RBC")
        assert it.value == 4.0

    def test_no_false_merge_two_items(self):
        items = _extract_and_parse(CASE_NO_FALSE_MERGE)
        names = [it.name for it in items]
        assert "WBC" in names
        assert "RBC" in names

    def test_name_without_value_wbc_not_found(self):
        items = _extract_and_parse(CASE_NAME_WITHOUT_VALUE)
        names = [it.name for it in items]
        assert "WBC" not in names

    def test_name_without_value_rbc_found(self):
        items = _extract_and_parse(CASE_NAME_WITHOUT_VALUE)
        it = _find(items, "RBC")
        assert it.value == 4.0

    def test_arrows_esr_value(self):
        items = _extract_and_parse(CASE_ARROWS)
        it = _find(items, "ESR")
        assert it.value == 28.0

    def test_arrows_esr_status(self):
        items = _extract_and_parse(CASE_ARROWS)
        it = _find(items, "ESR")
        assert it.status == "ВЫШЕ"

    def test_comparator_ref_value(self):
        items = _extract_and_parse(CASE_COMPARATOR_REF)
        it = _find(items, "CRP")
        assert it.value == 0.5

    def test_comparator_ref_ref(self):
        items = _extract_and_parse(CASE_COMPARATOR_REF)
        it = _find(items, "CRP")
        assert it.ref is not None

    def test_comparator_ref_unit(self):
        items = _extract_and_parse(CASE_COMPARATOR_REF)
        it = _find(items, "CRP")
        assert "мг/л" in it.unit


# ============================================================
# Регрессия: существующие golden cases не сломаны
# ============================================================
# Импортируем данные и тестовые утилиты из основного файла тестов

# Golden Case 1 (Helix CBC двухстрочный)
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

# Golden Case 2 (однострочный)
GOLDEN_2_ONELINE = """\
Нейтрофилы, % (NE%) 77 % 47.0 - 72.0
Лимфоциты, % (LY%) 18 % 19.0 - 37.0
Моноциты, % (MO%) 5 % 3.0 - 12.0
Эозинофилы, % (EO%) 0 % 1.0 - 5.0
Базофилы, % (BA%) 0.5 % 0.0 - 1.2
"""

# Golden Case 3 (биохимия)
GOLDEN_3_BIOCHEM = """\
АЛТ (ALT) 45 Ед/л 10 - 40
АСТ (AST) 32 Ед/л 10 - 40
Билирубин общий (TBIL) 18.5 мкмоль/л 3.4 - 20.5
Креатинин (CREA) 95 мкмоль/л 62 - 106
Мочевина (UREA) 5.2 ммоль/л 2.8 - 7.2
Глюкоза (GLUC) 5.8 ммоль/л 3.9 - 6.1
"""

# Golden Case 10 (смешанный)
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


class TestMultiLineNoRegression:
    """Регрессия: существующие golden cases не сломаны."""

    # Golden 1: Helix CBC
    def test_golden1_wbc(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "WBC")
        assert it.value == 8.23

    def test_golden1_rbc(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "RBC")
        assert it.value == 4.0

    def test_golden1_hgb(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "HGB")
        assert it.value == 120.0

    def test_golden1_hct(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "HCT")
        assert it.value == 34.7
        assert it.status == "НИЖЕ"

    def test_golden1_plt(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "PLT")
        assert it.value == 199.0

    def test_golden1_esr(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        it = _find(items, "ESR")
        assert it.value == 28.0
        assert it.status == "ВЫШЕ"

    def test_golden1_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_1_HELIX_CBC)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0

    # Golden 2: Однострочный
    def test_golden2_ne_above(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        it = _find(items, "NE%")
        assert it.value == 77.0
        assert it.status == "ВЫШЕ"

    def test_golden2_ly_below(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        it = _find(items, "LY%")
        assert it.value == 18.0
        assert it.status == "НИЖЕ"

    def test_golden2_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_2_ONELINE)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0

    # Golden 3: Биохимия
    def test_golden3_alt(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        it = _find(items, "ALT")
        assert it.value == 45.0
        assert it.status == "ВЫШЕ"

    def test_golden3_crea(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        it = _find(items, "CREA")
        assert it.value == 95.0
        assert it.status == "В НОРМЕ"

    def test_golden3_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_3_BIOCHEM)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0

    # Golden 10: Смешанный
    def test_golden10_wbc(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "WBC")
        assert it.value == 6.5

    def test_golden10_esr(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "ESR")
        assert it.value == 15.0
        assert it.status == "В НОРМЕ"

    def test_golden10_plt(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        it = _find(items, "PLT")
        assert it.value == 220.0

    def test_golden10_no_suspicious(self):
        items = _extract_and_parse(GOLDEN_10_MIXED)
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0


