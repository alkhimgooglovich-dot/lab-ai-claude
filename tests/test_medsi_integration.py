"""
Интеграционный тест для PDF МЕДСИ — полный пайплайн.

PDF: Клинический_анализ_крови_1767160017210.pdf  →  tests/fixtures/medsi_cbc.pdf

Проверяем:
  1. Извлечение текста из PDF (try_extract_text_from_pdf_bytes)
  2. Автоматический выбор МЕДСИ-экстрактора (_smart_to_candidates)
  3. Парсинг показателей (parse_with_fallback)
  4. Корректность 8 ключевых показателей (value, ref, status)
  5. Отсутствие мусора ('^', '*', пробелы, склейки)
  6. Метрики качества: suspicious_count == 0, valid_value_count >= 15
"""

import sys
import re
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import (
    try_extract_text_from_pdf_bytes,
    _smart_to_candidates,
    parse_with_fallback,
    assign_confidence,
    Item,
)
from parsers.quality import evaluate_parse_quality


# ============================
# Путь к тестовому PDF
# ============================
TEST_PDF = PROJECT_ROOT / "tests" / "fixtures" / "medsi_cbc.pdf"


# ============================
# Ожидаемые значения (8 ключевых показателей)
# ============================
EXPECTED = {
    "WBC": {
        "value": 4.78,
        "ref_low": 4.50,
        "ref_high": 11.00,
        "status": "В НОРМЕ",
    },
    "RBC": {
        "value": 5.33,
        "ref_low": 4.30,
        "ref_high": 5.70,
        "status": "В НОРМЕ",
    },
    "HGB": {
        "value": 152.0,
        "status": "В НОРМЕ",
    },
    "HCT": {
        "value": 46.5,
        "status": "В НОРМЕ",
    },
    "PLT": {
        "value": 213.0,
        "ref_low": 150.0,
        "ref_high": 400.0,
        "status": "В НОРМЕ",
    },
    "NE": {
        "value": 2.35,
        "status": "В НОРМЕ",
    },
    "LY%": {
        "value": 38.6,
        "status": "ВЫШЕ",
    },
    "ESR": {
        "value": 35.0,
        "status": "ВЫШЕ",
    },
}

# Альтернативные имена для поиска (NEU# → NE#, LYM% → LY%, СОЭ → ESR)
ALT_NAMES = {
    "NE": ("NE", "NE#", "NEU#", "NE_ABS", "NEU_ABS"),
    "LY%": ("LY%", "LYM%", "LY_PCT", "LYM_PCT"),
    "ESR": ("ESR", "СОЭ"),
}


# ============================
# Helpers
# ============================

def _get_pipeline_result():
    """
    Полный пайплайн:
      PDF bytes → pypdf text → _smart_to_candidates → parse_with_fallback → items
    """
    assert TEST_PDF.exists(), f"Тестовый PDF не найден: {TEST_PDF}"
    pdf_bytes = TEST_PDF.read_bytes()

    # Шаг 1: извлечение текста через pypdf
    raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)
    assert raw_text, "pypdf не смог извлечь текст из PDF МЕДСИ"

    # Шаг 2: auto-detect → candidates
    candidates = _smart_to_candidates(raw_text)
    assert candidates, "_smart_to_candidates вернула пустой результат"

    # Шаг 3: parse с fallback
    items = parse_with_fallback(candidates)
    assert items, "parse_with_fallback вернул пустой список"

    # Шаг 4: assign confidence
    assign_confidence(items)

    return items, candidates, raw_text


def _find_item(items: list, name: str) -> Item:
    """Находит Item по нормализованному имени (с учётом альтернатив)."""
    # Прямой поиск
    for it in items:
        if it.name == name:
            return it

    # Поиск по альтернативным именам
    alt_names = ALT_NAMES.get(name, ())
    for alt in alt_names:
        for it in items:
            if it.name == alt:
                return it

    available = sorted(set(it.name for it in items))
    raise AssertionError(
        f"Показатель '{name}' (альтернативы: {ALT_NAMES.get(name, ())}) "
        f"не найден.\nДоступные: {available}"
    )


# ============================================================
# ТЕСТЫ: Полный пайплайн — значения 8 ключевых показателей
# ============================================================

class TestMedsiPipelineValues:
    """Проверка значений 8 ключевых показателей из PDF МЕДСИ."""

    def test_wbc(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "WBC")
        assert it.value == 4.78, f"WBC value: ожидали 4.78, получили {it.value}"
        assert it.ref is not None, "WBC: ref не распознан"
        assert it.ref.low == 4.50, f"WBC ref_low: ожидали 4.50, получили {it.ref.low}"
        assert it.ref.high == 11.00, f"WBC ref_high: ожидали 11.00, получили {it.ref.high}"
        assert it.status == "В НОРМЕ", f"WBC status: ожидали 'В НОРМЕ', получили '{it.status}'"

    def test_rbc(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "RBC")
        assert it.value == 5.33, f"RBC value: ожидали 5.33, получили {it.value}"
        assert it.ref is not None, "RBC: ref не распознан"
        assert it.ref.low == 4.30, f"RBC ref_low: ожидали 4.30, получили {it.ref.low}"
        assert it.ref.high == 5.70, f"RBC ref_high: ожидали 5.70, получили {it.ref.high}"
        assert it.status == "В НОРМЕ", f"RBC status: ожидали 'В НОРМЕ', получили '{it.status}'"

    def test_hgb(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "HGB")
        assert it.value == 152.0, f"HGB value: ожидали 152.0, получили {it.value}"
        assert it.status == "В НОРМЕ", f"HGB status: ожидали 'В НОРМЕ', получили '{it.status}'"

    def test_hct(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "HCT")
        assert it.value == 46.5, f"HCT value: ожидали 46.5, получили {it.value}"
        assert it.status == "В НОРМЕ", f"HCT status: ожидали 'В НОРМЕ', получили '{it.status}'"

    def test_plt(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "PLT")
        assert it.value == 213.0, f"PLT value: ожидали 213.0, получили {it.value}"
        assert it.ref is not None, "PLT: ref не распознан"
        assert it.ref.low == 150.0, f"PLT ref_low: ожидали 150.0, получили {it.ref.low}"
        assert it.ref.high == 400.0, f"PLT ref_high: ожидали 400.0, получили {it.ref.high}"
        assert it.status == "В НОРМЕ", f"PLT status: ожидали 'В НОРМЕ', получили '{it.status}'"

    def test_neu_abs(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "NE")
        assert it.value == 2.35, f"NE value: ожидали 2.35, получили {it.value}"
        assert it.status == "В НОРМЕ", f"NE status: ожидали 'В НОРМЕ', получили '{it.status}'"

    def test_lym_percent(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "LY%")
        assert it.value == 38.6, f"LY% value: ожидали 38.6, получили {it.value}"
        assert it.status == "ВЫШЕ", f"LY% status: ожидали 'ВЫШЕ', получили '{it.status}'"

    def test_esr(self):
        items, _, _ = _get_pipeline_result()
        it = _find_item(items, "ESR")
        assert it.value == 35.0, f"ESR value: ожидали 35.0, получили {it.value}"
        assert it.status == "ВЫШЕ", f"ESR status: ожидали 'ВЫШЕ', получили '{it.status}'"


# ============================================================
# ТЕСТЫ: Статусы для всех 8 показателей (сводный)
# ============================================================

class TestMedsiPipelineStatuses:
    """Сводная проверка статусов для всех ожидаемых показателей."""

    def test_all_expected_statuses(self):
        items, _, _ = _get_pipeline_result()
        for name, expected in EXPECTED.items():
            it = _find_item(items, name)
            assert it.status == expected["status"], (
                f"{name}: ожидали статус '{expected['status']}', "
                f"получили '{it.status}'"
            )

    def test_all_expected_values(self):
        items, _, _ = _get_pipeline_result()
        for name, expected in EXPECTED.items():
            it = _find_item(items, name)
            assert it.value == expected["value"], (
                f"{name}: ожидали value={expected['value']}, получили {it.value}"
            )


# ============================================================
# ТЕСТЫ: Отсутствие мусора
# ============================================================

class TestMedsiNoGarbage:
    """Ни одно значение не должно содержать мусор."""

    def test_no_caret_in_values(self):
        """Ни в одном item.value не должно быть '^'."""
        items, _, _ = _get_pipeline_result()
        for it in items:
            if it.value is not None:
                val_str = f"{it.value:g}"
                assert "^" not in val_str, (
                    f"{it.name}: значение содержит '^': '{val_str}'"
                )

    def test_no_asterisk_in_values(self):
        """Ни в одном item.value не должно быть '*'."""
        items, _, _ = _get_pipeline_result()
        for it in items:
            if it.value is not None:
                val_str = f"{it.value:g}"
                assert "*" not in val_str, (
                    f"{it.name}: значение содержит '*': '{val_str}'"
                )

    def test_no_spaces_in_values(self):
        """Ни в одном item.value не должно быть пробелов."""
        items, _, _ = _get_pipeline_result()
        for it in items:
            if it.value is not None:
                val_str = f"{it.value:g}"
                assert " " not in val_str, (
                    f"{it.name}: значение содержит пробел: '{val_str}'"
                )

    def test_no_glued_ref_value(self):
        """Нет склеек типа '150-400213' в ref_text."""
        items, _, _ = _get_pipeline_result()
        for it in items:
            if it.ref_text:
                ref_clean = it.ref_text.replace(" ", "").replace("–", "-").replace("—", "-")
                # Допустимые форматы: "число-число", "<число", "<=число", ">число", ">=число"
                is_valid = bool(
                    re.match(r"^-?\d+(\.\d+)?--?\d+(\.\d+)?$", ref_clean)
                    or re.match(r"^(<=|>=|<|>)-?\d+(\.\d+)?$", ref_clean)
                )
                assert is_valid, (
                    f"{it.name}: невалидный ref_text '{it.ref_text}' "
                    f"(очищенный: '{ref_clean}')"
                )

    def test_no_10_caret_in_candidates(self):
        """В кандидатах не должно быть подстроки '10^' (мусор от pypdf)."""
        _, candidates, _ = _get_pipeline_result()
        assert "10^" not in candidates, (
            f"Найдена подстрока '10^' в кандидатах"
        )


# ============================================================
# ТЕСТЫ: Метрики качества
# ============================================================

class TestMedsiQualityMetrics:
    """Проверка метрик качества парсинга для PDF МЕДСИ."""

    def test_suspicious_count_zero(self):
        """suspicious_count должен быть 0 для корректно распознанного PDF."""
        items, _, _ = _get_pipeline_result()
        quality = evaluate_parse_quality(items)
        assert quality["suspicious_count"] == 0, (
            f"suspicious_count = {quality['suspicious_count']}, ожидали 0. "
            f"Полное quality: {quality}"
        )

    def test_valid_value_count_at_least_15(self):
        """valid_value_count должен быть >= 15 для МЕДСИ ОАК."""
        items, _, _ = _get_pipeline_result()
        quality = evaluate_parse_quality(items)
        assert quality["valid_value_count"] >= 15, (
            f"valid_value_count = {quality['valid_value_count']}, ожидали >= 15. "
            f"Полное quality: {quality}"
        )

    def test_coverage_score_above_threshold(self):
        """coverage_score должен быть >= 0.6 (нет необходимости в fallback)."""
        items, _, _ = _get_pipeline_result()
        quality = evaluate_parse_quality(items)
        assert quality["coverage_score"] >= 0.6, (
            f"coverage_score = {quality['coverage_score']}, ожидали >= 0.6. "
            f"Полное quality: {quality}"
        )

    def test_error_count_low(self):
        """error_count не должен превышать 3 (допуск на пустые/мусорные строки)."""
        items, _, _ = _get_pipeline_result()
        quality = evaluate_parse_quality(items)
        assert quality["error_count"] <= 3, (
            f"error_count = {quality['error_count']}, ожидали <= 3. "
            f"Полное quality: {quality}"
        )


# ============================================================
# ТЕСТЫ: Общая целостность пайплайна
# ============================================================

class TestMedsiPipelineIntegrity:
    """Проверка общей целостности пайплайна для МЕДСИ."""

    def test_minimum_items_count(self):
        """Должно быть не менее 15 распознанных показателей."""
        items, _, _ = _get_pipeline_result()
        assert len(items) >= 15, (
            f"Получили {len(items)} показателей, ожидали >= 15"
        )

    def test_confidence_assigned(self):
        """Всем показателям должен быть назначен confidence."""
        items, _, _ = _get_pipeline_result()
        for it in items:
            assert hasattr(it, "confidence"), (
                f"{it.name}: отсутствует поле confidence"
            )

    def test_key_items_high_confidence(self):
        """Ключевые показатели должны иметь высокий confidence (>= 0.7)."""
        items, _, _ = _get_pipeline_result()
        for name in EXPECTED:
            it = _find_item(items, name)
            assert it.confidence >= 0.7, (
                f"{name}: confidence = {it.confidence}, ожидали >= 0.7"
            )

    def test_pypdf_extracts_text(self):
        """pypdf должен извлечь текст из PDF МЕДСИ."""
        pdf_bytes = TEST_PDF.read_bytes()
        raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)
        assert raw_text, "pypdf не смог извлечь текст"
        assert len(raw_text) > 100, f"Текст слишком короткий: {len(raw_text)} символов"

    def test_smart_candidates_detects_medsi(self):
        """_smart_to_candidates должна выбрать МЕДСИ-экстрактор."""
        pdf_bytes = TEST_PDF.read_bytes()
        raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)
        candidates = _smart_to_candidates(raw_text)
        assert candidates, "Кандидаты пустые"
        # Не должно быть мусора '10^'
        assert "10^" not in candidates, "Кандидаты содержат '10^'"
        # Должны быть чистые значения ключевых показателей
        assert "4.78" in candidates, "WBC=4.78 не найден в кандидатах"
        assert "5.33" in candidates, "RBC=5.33 не найден в кандидатах"
        assert "213" in candidates, "PLT=213 не найден в кандидатах"

