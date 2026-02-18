"""
Regression-тесты и расширение покрытия (Этап 2.2).

- TestRegressionDashNotScientific: дефисы/тире в диапазонах НЕ → ^
- TestScientificNotationNormalization: * и ~ → ^, дефисы — нет
- TestRefFormatParsing: парсинг разных форматов референсов
"""

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parsers.universal_extractor import _normalize_scientific_notation, universal_extract
from engine import parse_items_from_candidates, assign_confidence, parse_ref_range, status_by_range, Range


# ═══════════════════════════════════════════════════════
# Класс 1: Регрессия — дефис/тире НЕ оператор степени
# ═══════════════════════════════════════════════════════
class TestRegressionDashNotScientific:
    """Регрессия: _normalize_scientific_notation НЕ должна трогать дефисы/тире в диапазонах."""

    def test_space_dash_space(self):
        assert _normalize_scientific_notation("10 - 40") == "10 - 40"

    def test_no_space_dash(self):
        assert _normalize_scientific_notation("10-40") == "10-40"

    def test_en_dash(self):
        assert _normalize_scientific_notation("10 \u2013 40") == "10 \u2013 40"

    def test_em_dash(self):
        assert _normalize_scientific_notation("10 \u2014 40") == "10 \u2014 40"

    def test_fractional_left(self):
        assert _normalize_scientific_notation("1.6 - 40") == "1.6 - 40"

    def test_fractional_range(self):
        assert _normalize_scientific_notation("0.5-1.5") == "0.5-1.5"

    def test_three_digit_range(self):
        assert _normalize_scientific_notation("150 - 400") == "150 - 400"

    def test_alt_end_to_end_no_false_exponent(self):
        """АЛТ 45 при норме 10-40: ref = '10-40', НЕ '10^40'."""
        text = "АЛТ (ALT) 45 Ед/л 10 - 40"
        candidates = universal_extract(text)
        assert candidates, "universal_extract вернул пустой результат"
        assert "10^40" not in candidates, f"Баг вернулся! candidates={candidates}"
        # ref должен содержать «10-40» (с или без пробелов)
        flat = candidates.replace("\t", " ")
        assert "10-40" in flat or "10 - 40" in flat, f"Нет ref 10-40: {candidates}"


# ═══════════════════════════════════════════════════════
# Класс 2: Нормализация научной нотации (* и ~ → ^)
# ═══════════════════════════════════════════════════════
class TestScientificNotationNormalization:
    """Проверяем: * и ~ → ^, дефисы → НЕ трогать."""

    def test_star(self):
        assert "10^9" in _normalize_scientific_notation("10*9")

    def test_star_spaces(self):
        assert "10^9" in _normalize_scientific_notation("10 * 9")

    def test_tilde(self):
        assert "10^9" in _normalize_scientific_notation("10~9")

    def test_tilde_spaces(self):
        assert "10^9" in _normalize_scientific_notation("10 ~ 9")

    def test_star_two_digit_exp(self):
        assert "10^12" in _normalize_scientific_notation("10*12")

    def test_tilde_two_digit_exp(self):
        assert "10^12" in _normalize_scientific_notation("10~12")

    def test_superscript_9(self):
        result = _normalize_scientific_notation("10⁹")
        assert "10^9" in result

    def test_superscript_0(self):
        result = _normalize_scientific_notation("10⁰")
        assert "10^0" in result

    def test_dash_NOT_normalized(self):
        """Ключевое: дефис НЕ оператор степени."""
        assert "10^9" not in _normalize_scientific_notation("10-9")

    def test_dash_spaces_NOT_normalized(self):
        assert "10^9" not in _normalize_scientific_notation("10 - 9")

    def test_wbc_end_to_end_no_false_10_pow_10(self):
        """WBC 8.23, норма 4.00-10.00: в кандидатах НЕТ '10^10'."""
        text = "Лейкоциты (WBC) 8.23 *10^9/л 4.00 - 10.00"
        candidates = universal_extract(text)
        assert candidates
        assert "10^10" not in candidates, f"Ложная нотация! candidates={candidates}"


# ═══════════════════════════════════════════════════════
# Класс 3: Парсинг разных форматов референсов
# ═══════════════════════════════════════════════════════
class TestRefFormatParsing:
    """Форматы референсов: a-b, <x, >x, ≤x, ≥x, до x."""

    # --- Юнит-тесты parse_ref_range ---
    def test_range_simple(self):
        r = parse_ref_range("10-40")
        assert r is not None and r.low == 10.0 and r.high == 40.0

    def test_range_decimal(self):
        r = parse_ref_range("3.80-5.10")
        assert r is not None and r.low == 3.8 and r.high == 5.1

    def test_less_than(self):
        r = parse_ref_range("<20")
        assert r is not None and r.low is None and r.high == 20.0

    def test_greater_than(self):
        r = parse_ref_range(">5.0")
        assert r is not None and r.low == 5.0 and r.high is None

    def test_less_equal(self):
        r = parse_ref_range("<=20")
        assert r is not None and r.low is None and r.high == 20.0

    def test_greater_equal(self):
        r = parse_ref_range(">=5.0")
        assert r is not None and r.low == 5.0 and r.high is None

    # --- Сквозные тесты: universal_extract + формат рефа ---
    def test_extract_range_ref(self):
        text = "Глюкоза (GLU) 5.2 ммоль/л 3.9 - 6.1"
        candidates = universal_extract(text)
        assert candidates
        flat = candidates.replace("\t", " ")
        assert "3.9-6.1" in flat or "3.9 - 6.1" in flat

    def test_extract_less_than_ref(self):
        text = "СРБ (CRP) 3.5 мг/л <5.0"
        candidates = universal_extract(text)
        assert candidates
        assert "<5" in candidates or "<=5" in candidates

    def test_extract_greater_than_ref(self):
        text = "Витамин D 18.5 нг/мл >30"
        candidates = universal_extract(text)
        assert candidates
        assert ">30" in candidates or ">=30" in candidates

    def test_extract_unicode_le(self):
        text = "Мочевая кислота 350 мкмоль/л ≤420"
        candidates = universal_extract(text)
        assert candidates
        assert "<=420" in candidates or "≤420" in candidates

    def test_extract_unicode_ge(self):
        text = "Ферритин 25 нг/мл ≥20"
        candidates = universal_extract(text)
        assert candidates
        assert ">=20" in candidates or "≥20" in candidates

    def test_russian_do_format(self):
        """Формат 'до x' — парсер поддерживает канонизацию «до X» → «<X»."""
        text = "Билирубин общий 15.3 мкмоль/л до 21"
        candidates = universal_extract(text)
        assert candidates, "universal_extract вернул пустой результат для 'до 21'"
        assert "<21" in candidates or "21" in candidates


# ═══════════════════════════════════════════════════════
# Класс 4: Этап 3.1 — референсы вида «до x»
# ═══════════════════════════════════════════════════════
class TestDoRefFormat:
    """Этап 3.1: референсы вида 'до x'."""

    # --- parse_ref_range ---
    def test_parse_do_5(self):
        r = parse_ref_range("до 5")
        assert r == Range(low=None, high=5.0)

    def test_parse_do_5_comma(self):
        r = parse_ref_range("до 5,0")
        assert r == Range(low=None, high=5.0)

    def test_parse_do_5_dot(self):
        r = parse_ref_range("до 5.0")
        assert r == Range(low=None, high=5.0)

    def test_parse_do_no_space(self):
        r = parse_ref_range("до5")
        assert r == Range(low=None, high=5.0)

    def test_parse_do_capital(self):
        r = parse_ref_range("До 10")
        assert r == Range(low=None, high=10.0)

    def test_parse_do_decimal(self):
        r = parse_ref_range("до 0.50")
        assert r == Range(low=None, high=0.5)

    # --- status_by_range с «до»-референсом ---
    def test_status_below_do_ref(self):
        r = parse_ref_range("до 5")
        assert status_by_range(3.0, r) == "В НОРМЕ"

    def test_status_equal_do_ref(self):
        """Граничное: значение == верхняя граница → В НОРМЕ."""
        r = parse_ref_range("до 5")
        assert status_by_range(5.0, r) == "В НОРМЕ"

    def test_status_above_do_ref(self):
        r = parse_ref_range("до 5")
        assert status_by_range(6.0, r) == "ВЫШЕ"

    # --- Не сломали существующее ---
    def test_existing_range_still_works(self):
        r = parse_ref_range("3.80-5.10")
        assert r == Range(low=3.8, high=5.1)

    def test_existing_le_still_works(self):
        r = parse_ref_range("<=20")
        assert r == Range(low=None, high=20.0)

    def test_existing_ge_still_works(self):
        r = parse_ref_range(">=5.0")
        assert r == Range(low=5.0, high=None)

    def test_existing_lt_still_works(self):
        r = parse_ref_range("<5")
        assert r == Range(low=None, high=5.0)
