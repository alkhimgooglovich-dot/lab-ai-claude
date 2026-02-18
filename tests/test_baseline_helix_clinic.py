"""
Регрессионный тест baseline-парсера для Helix / КЛИНИКА.

PDF: 0333285a-adec-4b5d-9c25-52811a5c1747.pdf
Ожидаемые значения зафиксированы из корректного baseline (commit baseline_helix_stable).

Тест ДОЛЖЕН ПАДАТЬ, если парсер начинает выдавать мусор:
  - "28 8" вместо "28"
  - "150-400213" (склейка ref+value)
  - пропущены ключевые показатели ОАК
"""

import sys
import re
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import (
    try_extract_text_from_pdf_bytes,
    helix_table_to_candidates,
    parse_items_from_candidates,
    Item,
)

# ============================
# Путь к тестовому PDF
# ============================
TEST_PDF = PROJECT_ROOT / "tests" / "fixtures" / "0333285a-adec-4b5d-9c25-52811a5c1747.pdf"

# ============================
# Ожидаемые значения baseline
# ============================
EXPECTED = {
    "WBC":  {"value": 8.23,  "status_in": ("В НОРМЕ",)},
    "RBC":  {"value": 4.00,  "status_in": ("В НОРМЕ",)},
    "HGB":  {"value": 120.0, "status_in": ("В НОРМЕ",)},
    "HCT":  {"value": 34.7,  "status_in": ("НИЖЕ",)},
    "ESR":  {"value": 28.0,  "status_in": ("ВЫШЕ",)},
    "PLT":  {"value": 199.0, "status_in": ("В НОРМЕ",)},
    "NE%":  {"value": 77.0,  "status_in": ("ВЫШЕ",)},
    "LY%":  {"value": 18.0,  "status_in": ("НИЖЕ",)},
}

# Минимальное количество показателей в baseline-разборе
MIN_ITEMS_COUNT = 15


def _get_baseline_items() -> list:
    """
    Прогоняет PDF через baseline-парсер (без OCR, только pypdf).
    Возвращает список Item.
    """
    assert TEST_PDF.exists(), f"Тестовый PDF не найден: {TEST_PDF}"
    pdf_bytes = TEST_PDF.read_bytes()

    # Извлекаем текст через pypdf (без сети)
    raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)
    assert raw_text, "pypdf не смог извлечь текст из PDF"

    # Собираем кандидатов
    candidates = helix_table_to_candidates(raw_text)
    assert candidates, "helix_table_to_candidates вернул пустой результат"

    # Парсим показатели
    items = parse_items_from_candidates(candidates)
    return items


def _find_item(items: list, name: str) -> Item:
    """Находит Item по нормализованному имени."""
    for it in items:
        if it.name == name:
            return it
    available = [it.name for it in items]
    raise AssertionError(f"Показатель '{name}' не найден. Доступные: {available}")


# ============================================================
# ТЕСТЫ
# ============================================================

class TestBaselineHelixClinic:
    """Регрессионные тесты baseline-парсера (Helix / КЛИНИКА)."""

    def test_minimum_items_count(self):
        """Парсер должен вернуть не менее MIN_ITEMS_COUNT показателей."""
        items = _get_baseline_items()
        assert len(items) >= MIN_ITEMS_COUNT, (
            f"Ожидали >= {MIN_ITEMS_COUNT} показателей, получили {len(items)}"
        )

    def test_wbc_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "WBC")
        assert it.value == 8.23, f"WBC: ожидали 8.23, получили {it.value}"

    def test_rbc_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "RBC")
        assert it.value == 4.0, f"RBC: ожидали 4.0, получили {it.value}"

    def test_hgb_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "HGB")
        assert it.value == 120.0, f"HGB: ожидали 120.0, получили {it.value}"

    def test_hct_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "HCT")
        assert it.value == 34.7, f"HCT: ожидали 34.7, получили {it.value}"

    def test_esr_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "ESR")
        assert it.value == 28.0, f"ESR: ожидали 28.0, получили {it.value}"

    def test_plt_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "PLT")
        assert it.value == 199.0, f"PLT: ожидали 199.0, получили {it.value}"

    def test_ne_percent_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "NE%")
        assert it.value == 77.0, f"NE%: ожидали 77.0, получили {it.value}"

    def test_ly_percent_value(self):
        items = _get_baseline_items()
        it = _find_item(items, "LY%")
        assert it.value == 18.0, f"LY%: ожидали 18.0, получили {it.value}"

    def test_statuses(self):
        """Проверяем статусы для всех ожидаемых показателей."""
        items = _get_baseline_items()
        for name, expected in EXPECTED.items():
            it = _find_item(items, name)
            assert it.status in expected["status_in"], (
                f"{name}: ожидали статус из {expected['status_in']}, "
                f"получили '{it.status}'"
            )

    def test_no_garbage_values(self):
        """
        Ни одно значение не должно содержать мусор:
        - value с пробелами (например "28 8")
        - ref+value склейка ("150-400213")
        """
        items = _get_baseline_items()
        for it in items:
            if it.value is not None:
                val_str = f"{it.value:g}"
                # Значение не должно содержать пробелов
                assert " " not in val_str, (
                    f"{it.name}: значение содержит пробел: '{val_str}'"
                )

            # ref_text не должен содержать склеенных данных
            if it.ref_text:
                ref_clean = it.ref_text.replace(" ", "").replace("–", "-").replace("—", "-")
                # Нормальный формат: "3.80-5.10", "<=20", "0.00-0.08"
                is_valid_range = bool(
                    re.match(r"^-?\d+(\.\d+)?--?\d+(\.\d+)?$", ref_clean)
                    or re.match(r"^(<=|>=|<|>)-?\d+(\.\d+)?$", ref_clean)
                )
                assert is_valid_range, (
                    f"{it.name}: невалидный ref_text '{it.ref_text}' "
                    f"(очищенный: '{ref_clean}')"
                )

    def test_all_expected_values(self):
        """Сводная проверка всех ожидаемых значений."""
        items = _get_baseline_items()
        for name, expected in EXPECTED.items():
            it = _find_item(items, name)
            assert it.value == expected["value"], (
                f"{name}: ожидали {expected['value']}, получили {it.value}"
            )





