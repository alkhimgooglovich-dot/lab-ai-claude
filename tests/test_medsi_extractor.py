"""
Тесты МЕДСИ-экстрактора кандидатов.

Проверяем:
  1. Детектор is_medsi_format корректно определяет МЕДСИ
  2. medsi_inline_to_candidates строит правильные TSV-кандидаты
  3. НЕТ подстрок "10^", НЕТ склеек типа "150-400213"
  4. Интеграция: parse_items_from_candidates корректно разбирает кандидатов
  5. Ожидаемые значения: WBC=4.78, RBC=5.33, PLT=213, СОЭ=35, LYM%=38.6
"""

import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parsers.medsi_extractor import (
    is_medsi_format,
    medsi_inline_to_candidates,
    _split_ref_and_value,
    _map_medsi_code,
)
from engine import parse_items_from_candidates, Item

# ============================
# Загрузка фикстуры
# ============================
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "medsi_pypdf_text.txt"
MEDSI_TEXT = FIXTURE_PATH.read_text(encoding="utf-8")


# ============================
# Ожидаемые значения МЕДСИ
# ============================
EXPECTED = {
    "WBC":  {"value": 4.78,  "ref": "4.50-11.00", "status_in": ("В НОРМЕ",)},
    "RBC":  {"value": 5.33,  "ref": "4.30-5.70",  "status_in": ("В НОРМЕ",)},
    "HGB":  {"value": 152.0, "ref": "132-173",     "status_in": ("В НОРМЕ",)},
    "HCT":  {"value": 46.5,  "ref": "39.0-49.0",   "status_in": ("В НОРМЕ",)},
    "PLT":  {"value": 213.0, "ref": "150-400",     "status_in": ("В НОРМЕ",)},
    "ESR":  {"value": 35.0,  "ref": "0-15",        "status_in": ("ВЫШЕ",)},
    "NE%":  {"value": 49.2,  "ref": "47.00-72.00", "status_in": ("В НОРМЕ",)},
    "LY%":  {"value": 38.6,  "ref": "19-37",       "status_in": ("ВЫШЕ",)},
}


# ============================================================
# ТЕСТЫ: Детектор формата
# ============================================================
class TestMedsiDetector:

    def test_medsi_text_detected(self):
        """Фикстура МЕДСИ должна детектироваться как МЕДСИ."""
        assert is_medsi_format(MEDSI_TEXT), "МЕДСИ-текст не распознан"

    def test_helix_text_not_detected(self):
        """Текст с табуляциями Helix НЕ должен детектироваться как МЕДСИ."""
        helix = "Лейкоциты (WBC)\t8.23\t4.00-10.00\t*10^9/л\n"
        assert not is_medsi_format(helix)

    def test_empty_text_not_detected(self):
        assert not is_medsi_format("")

    def test_garbage_not_detected(self):
        assert not is_medsi_format("Просто какой-то текст без лабораторных данных")


# ============================================================
# ТЕСТЫ: Разделение ref + value
# ============================================================
class TestSplitRefAndValue:

    def test_decimal_ref_decimal_value(self):
        ref, val = _split_ref_and_value("4.50-11.004.78")
        assert ref == "4.50-11.00", f"ref={ref}"
        assert val == "4.78", f"val={val}"

    def test_integer_ref_integer_value(self):
        ref, val = _split_ref_and_value("150-400213")
        assert ref == "150-400", f"ref={ref}"
        assert val == "213", f"val={val}"

    def test_integer_ref_with_flag(self):
        ref, val = _split_ref_and_value("0-15↑ 35")
        assert ref == "0-15", f"ref={ref}"
        assert val == "35", f"val={val}"

    def test_integer_ref_decimal_value_with_flag(self):
        ref, val = _split_ref_and_value("19-37↑ 38.6")
        assert ref == "19-37", f"ref={ref}"
        assert val == "38.6", f"val={val}"

    def test_decimal1_ref(self):
        ref, val = _split_ref_and_value("39.0-49.046.5")
        assert ref == "39.0-49.0", f"ref={ref}"
        assert val == "46.5", f"val={val}"

    def test_small_decimal_ref(self):
        ref, val = _split_ref_and_value("0.0-0.50")
        assert ref == "0.0-0.5", f"ref={ref}"
        assert val == "0", f"val={val}"

    def test_small_decimal2_ref(self):
        ref, val = _split_ref_and_value("0.00-0.030")
        assert ref == "0.00-0.03", f"ref={ref}"
        assert val == "0", f"val={val}"

    def test_decimal1_middle(self):
        ref, val = _split_ref_and_value("8.8-12.29.4")
        assert ref == "8.8-12.2", f"ref={ref}"
        assert val == "9.4", f"val={val}"

    def test_decimal1_pct(self):
        ref, val = _split_ref_and_value("0.17-0.320.2")
        assert ref == "0.17-0.32", f"ref={ref}"
        assert val == "0.2", f"val={val}"

    def test_decimal2_large(self):
        ref, val = _split_ref_and_value("47.00-72.0049.2")
        assert ref == "47.00-72.00", f"ref={ref}"
        assert val == "49.2", f"val={val}"

    def test_integer_3digit(self):
        ref, val = _split_ref_and_value("132-173152")
        assert ref == "132-173", f"ref={ref}"
        assert val == "152", f"val={val}"

    def test_integer_3digit_2(self):
        ref, val = _split_ref_and_value("319.0-356.0327")
        assert ref == "319.0-356.0", f"ref={ref}"
        assert val == "327", f"val={val}"


# ============================================================
# ТЕСТЫ: Маппинг кодов
# ============================================================
class TestCodeMapping:

    def test_neu_percent(self):
        assert _map_medsi_code("NEU%") == "NE%"

    def test_lym_hash(self):
        assert _map_medsi_code("LYM#") == "LY#"

    def test_mono_percent(self):
        assert _map_medsi_code("MONO%") == "MO%"

    def test_wbc_unchanged(self):
        assert _map_medsi_code("WBC") == "WBC"

    def test_plt_unchanged(self):
        assert _map_medsi_code("PLT") == "PLT"


# ============================================================
# ТЕСТЫ: Кандидаты
# ============================================================
class TestMedsiCandidates:

    def test_candidates_not_empty(self):
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        assert candidates, "Кандидаты пустые"
        lines = candidates.splitlines()
        assert len(lines) >= 15, f"Ожидали >= 15 кандидатов, получили {len(lines)}"

    def test_no_garbled_10_caret(self):
        """Кандидаты НЕ должны содержать '10^' (мусор от helix-парсера)."""
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        assert "10^" not in candidates, f"Найдена подстрока '10^' в кандидатах:\n{candidates}"

    def test_no_glued_ref_value(self):
        """Кандидаты НЕ должны содержать склейки типа '150-400213'."""
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        for line in candidates.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                ref = parts[2]
                # Ref должен быть чистым диапазоном, без приклеенного значения
                ref_clean = ref.replace(" ", "").replace("–", "-").replace("—", "-")
                is_valid = bool(
                    re.match(r"^-?\d+(\.\d+)?--?\d+(\.\d+)?$", ref_clean)
                    or re.match(r"^(<=|>=|<|>)-?\d+(\.\d+)?$", ref_clean)
                )
                assert is_valid, f"Невалидный ref: '{ref}' в строке: {line}"

    def test_wbc_in_candidates(self):
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        assert "4.78" in candidates, "WBC value 4.78 не найден"
        assert "4.50-11.00" in candidates, "WBC ref 4.50-11.00 не найден"

    def test_rbc_in_candidates(self):
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        assert "5.33" in candidates, "RBC value 5.33 не найден"
        assert "4.30-5.70" in candidates, "RBC ref 4.30-5.70 не найден"

    def test_plt_in_candidates(self):
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        # PLT: value=213, ref=150-400 (разделены, не "150-400213")
        lines = candidates.splitlines()
        plt_found = False
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 3 and "213" in parts[1]:
                assert parts[2].strip() == "150-400", f"PLT ref неверный: '{parts[2]}'"
                plt_found = True
        assert plt_found, f"PLT строка не найдена в кандидатах:\n{candidates}"

    def test_soe_in_candidates(self):
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        assert "35" in candidates, "СОЭ value 35 не найден"
        assert "0-15" in candidates, "СОЭ ref 0-15 не найден"

    def test_lym_percent_in_candidates(self):
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        assert "38.6" in candidates, "LYM% value 38.6 не найден"


# ============================================================
# ТЕСТЫ: Интеграция (candidates → parse_items)
# ============================================================
class TestMedsiIntegration:

    def _get_items(self) -> list:
        candidates = medsi_inline_to_candidates(MEDSI_TEXT)
        return parse_items_from_candidates(candidates)

    def _find(self, items, name):
        for it in items:
            if it.name == name:
                return it
        available = [it.name for it in items]
        raise AssertionError(f"Показатель '{name}' не найден. Доступные: {available}")

    def test_minimum_items_count(self):
        items = self._get_items()
        assert len(items) >= 15, f"Получили {len(items)} показателей"

    def test_wbc_value(self):
        items = self._get_items()
        it = self._find(items, "WBC")
        assert it.value == 4.78, f"WBC: получили {it.value}"

    def test_rbc_value(self):
        items = self._get_items()
        it = self._find(items, "RBC")
        assert it.value == 5.33, f"RBC: получили {it.value}"

    def test_hgb_value(self):
        items = self._get_items()
        it = self._find(items, "HGB")
        assert it.value == 152.0, f"HGB: получили {it.value}"

    def test_plt_value(self):
        items = self._get_items()
        it = self._find(items, "PLT")
        assert it.value == 213.0, f"PLT: получили {it.value}"

    def test_esr_value(self):
        items = self._get_items()
        it = self._find(items, "ESR")
        assert it.value == 35.0, f"ESR: получили {it.value}"

    def test_esr_status_above(self):
        items = self._get_items()
        it = self._find(items, "ESR")
        assert it.status == "ВЫШЕ", f"ESR status: получили '{it.status}'"

    def test_lym_percent_value(self):
        items = self._get_items()
        it = self._find(items, "LY%")
        assert it.value == 38.6, f"LY%: получили {it.value}"

    def test_lym_percent_status_above(self):
        items = self._get_items()
        it = self._find(items, "LY%")
        assert it.status == "ВЫШЕ", f"LY% status: получили '{it.status}'"

    def test_all_expected_values(self):
        """Сводная проверка всех ожидаемых значений."""
        items = self._get_items()
        for name, expected in EXPECTED.items():
            it = self._find(items, name)
            assert it.value == expected["value"], (
                f"{name}: ожидали {expected['value']}, получили {it.value}"
            )

    def test_all_expected_statuses(self):
        """Проверяем статусы для ключевых показателей."""
        items = self._get_items()
        for name, expected in EXPECTED.items():
            it = self._find(items, name)
            assert it.status in expected["status_in"], (
                f"{name}: ожидали статус из {expected['status_in']}, "
                f"получили '{it.status}'"
            )

    def test_no_garbage_values(self):
        """Ни одно значение не должно содержать мусор."""
        items = self._get_items()
        for it in items:
            if it.value is not None:
                val_str = f"{it.value:g}"
                assert " " not in val_str, (
                    f"{it.name}: значение содержит пробел: '{val_str}'"
                )
            if it.ref_text:
                ref_clean = it.ref_text.replace(" ", "").replace("–", "-").replace("—", "-")
                is_valid = bool(
                    re.match(r"^-?\d+(\.\d+)?--?\d+(\.\d+)?$", ref_clean)
                    or re.match(r"^(<=|>=|<|>)-?\d+(\.\d+)?$", ref_clean)
                )
                assert is_valid, (
                    f"{it.name}: невалидный ref_text '{it.ref_text}'"
                )


# ============================================================
# ТЕСТ: _smart_to_candidates в engine.py
# ============================================================
class TestSmartCandidates:

    def test_smart_uses_medsi_for_medsi_text(self):
        """_smart_to_candidates должна использовать МЕДСИ-экстрактор."""
        from engine import _smart_to_candidates
        candidates = _smart_to_candidates(MEDSI_TEXT)
        assert candidates, "Кандидаты пустые"
        # Не должно быть мусора
        assert "10^" not in candidates
        # Должны быть чистые значения
        assert "4.78" in candidates

    def test_smart_uses_helix_for_helix_text(self):
        """Для текста Helix _smart_to_candidates должна использовать helix-экстрактор."""
        from engine import _smart_to_candidates
        helix_text = "Лейкоциты (WBC)\n8.23\n*10^9/л\n4.00 - 10.00"
        # Не МЕДСИ → helix path
        candidates = _smart_to_candidates(helix_text)
        # Результат может быть пустым (short text), но ошибки быть не должно
        assert isinstance(candidates, str)





