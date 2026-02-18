"""
Тесты для parsers/line_scorer.py.

Проверяем:
  - score_line на мусорных строках → score < 0.3
  - score_line на строках с показателями → score >= 0.5
  - is_noise на типовых служебных строках
  - has_numeric_value, has_ref_pattern, has_known_unit, has_known_biomarker
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parsers.line_scorer import (
    score_line,
    is_noise,
    has_numeric_value,
    has_ref_pattern,
    has_known_unit,
    has_known_biomarker,
)


# ============================================================
# Тесты: score_line — мусорные строки (< 0.3)
# ============================================================
class TestScoreLineGarbage:

    def test_empty_string(self):
        assert score_line("") == 0.0

    def test_noise_license(self):
        assert score_line("Лицензия № 12345 от 01.01.2020") < 0.3

    def test_noise_eqas(self):
        assert score_line("EQAS External Quality Assessment") < 0.3

    def test_noise_page_marker(self):
        assert score_line("--- PAGE 1 ---") == 0.0

    def test_noise_patient_info(self):
        assert score_line("Пациент: Иванов Иван Иванович") < 0.3

    def test_noise_date(self):
        assert score_line("Дата: 01.01.2025") < 0.3

    def test_noise_sgs(self):
        assert score_line("SGS Vostok Limited") < 0.3

    def test_noise_order(self):
        assert score_line("Заказ № 12345678") < 0.3

    def test_noise_doctor(self):
        assert score_line("Врач: Петров А.В.") < 0.3

    def test_noise_just_number(self):
        assert score_line("12345") == 0.0

    def test_noise_short(self):
        assert score_line("ab") == 0.0

    def test_noise_method(self):
        assert score_line("Метод и оборудование: анализатор XN-1000") < 0.3

    def test_noise_validation(self):
        assert score_line("Валидация проведена") < 0.3


# ============================================================
# Тесты: score_line — показатели (>= 0.5)
# ============================================================
class TestScoreLineIndicators:

    def test_wbc_two_line_value(self):
        # Строка-имя обычно не получает высокий score без числа,
        # но строка с числом и единицей — получает
        assert score_line("8.23 *10^9/л 4.00 - 10.00") >= 0.4

    def test_one_line_esr(self):
        assert score_line("Скорость оседания 28 мм/ч 2 - 20") >= 0.5

    def test_one_line_ne_percent(self):
        assert score_line("Нейтрофилы, % (NE%) 77 % 47.0 - 72.0") >= 0.5

    def test_one_line_alt(self):
        assert score_line("АЛТ (ALT) 45 Ед/л 10 - 40") >= 0.5

    def test_one_line_creatinine(self):
        assert score_line("Креатинин (CREA) 95 мкмоль/л 62 - 106") >= 0.5

    def test_one_line_glucose(self):
        assert score_line("Глюкоза (GLUC) 5.8 ммоль/л 3.9 - 6.1") >= 0.5

    def test_one_line_cholesterol(self):
        assert score_line("Холестерин общий (CHOL) 6.2 ммоль/л 3.0 - 5.2") >= 0.5


# ============================================================
# Тесты: is_noise
# ============================================================
class TestIsNoise:

    def test_empty(self):
        assert is_noise("")

    def test_noise_license(self):
        assert is_noise("Лицензия № 12345")

    def test_noise_page_marker(self):
        assert is_noise("--- PAGE 1 ---")

    def test_noise_patient(self):
        assert is_noise("Пациент: Иванов")

    def test_noise_sgs(self):
        assert is_noise("SGS Vostok")

    def test_noise_validation(self):
        assert is_noise("Валидация результатов")

    def test_noise_order(self):
        assert is_noise("Заказ № 12345")

    def test_not_noise_wbc(self):
        assert not is_noise("Лейкоциты (WBC) 8.23 *10^9/л 4.00 - 10.00")

    def test_not_noise_esr(self):
        assert not is_noise("Скорость оседания 28 мм/ч 2 - 20")


# ============================================================
# Тесты: предикаты
# ============================================================
class TestPredicates:

    def test_has_numeric_value(self):
        assert has_numeric_value("значение 8.23")
        assert has_numeric_value("123")
        assert not has_numeric_value("текст без чисел")

    def test_has_ref_pattern(self):
        assert has_ref_pattern("4.00 - 10.00")
        assert has_ref_pattern("150-400")
        assert has_ref_pattern("<=5.0")
        assert has_ref_pattern(">=1.0")
        assert not has_ref_pattern("просто текст")

    def test_has_ref_pattern_do_format(self):
        """Этап 3.1: паттерн «до число» распознаётся как референс."""
        assert has_ref_pattern("до 5")
        assert has_ref_pattern("до 5.0")
        assert has_ref_pattern("До 10")
        assert has_ref_pattern("до5")

    def test_has_known_unit(self):
        assert has_known_unit("г/л")
        assert has_known_unit("8.23 *10^9/л")
        assert has_known_unit("результат: 28 мм/ч")
        assert not has_known_unit("просто текст")

    def test_has_known_biomarker(self):
        assert has_known_biomarker("Лейкоциты (WBC)")
        assert has_known_biomarker("Гемоглобин")
        assert has_known_biomarker("СОЭ")
        assert has_known_biomarker("ALT 45")
        assert not has_known_biomarker("Просто какой-то текст")


