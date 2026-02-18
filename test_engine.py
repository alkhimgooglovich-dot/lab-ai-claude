"""
Минимальные тесты для проверки парсинга и определения статусов.
Запуск: python test_engine.py
"""
import sys
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from engine import (
    parse_float,
    parse_ref_range,
    status_by_range,
    Range,
    parse_items_from_candidates,
)


def test_parse_float():
    """Тест парсинга чисел"""
    assert parse_float("4.00") == 4.0
    assert parse_float("199") == 199.0
    assert parse_float("28") == 28.0
    assert parse_float("34.7") == 34.7
    assert parse_float("15.2") == 15.2
    print("✓ parse_float работает корректно")


def test_parse_ref_range():
    """Тест парсинга референсных диапазонов"""
    # Обычные диапазоны
    r = parse_ref_range("3.80-5.10")
    assert r is not None
    assert r.low == 3.8
    assert r.high == 5.1
    
    r = parse_ref_range("150-400")
    assert r is not None
    assert r.low == 150.0
    assert r.high == 400.0
    
    r = parse_ref_range("2-20")
    assert r is not None
    assert r.low == 2.0
    assert r.high == 20.0
    
    r = parse_ref_range("35.0-45.0")
    assert r is not None
    assert r.low == 35.0
    assert r.high == 45.0
    
    # Защита от перепутанных low/high
    r = parse_ref_range("5.10-3.80")  # неправильный порядок
    assert r is not None
    assert r.low == 3.8  # должно быть исправлено
    assert r.high == 5.1
    
    print("✓ parse_ref_range работает корректно")


def test_status_by_range():
    """Тест определения статусов"""
    # Тест 1: RBC = 4.00 при норме 3.80–5.10 → В НОРМЕ
    r = Range(low=3.8, high=5.1)
    assert status_by_range(4.00, r) == "В НОРМЕ"
    
    # Тест 2: PLT = 199 при норме 150–400 → В НОРМЕ
    r = Range(low=150.0, high=400.0)
    assert status_by_range(199.0, r) == "В НОРМЕ"
    
    # Тест 3: СОЭ = 28 при норме 2–20 → ВЫШЕ
    r = Range(low=2.0, high=20.0)
    assert status_by_range(28.0, r) == "ВЫШЕ"
    
    # Тест 4: HCT = 34.7 при норме 35.0–45.0 → НИЖЕ
    r = Range(low=35.0, high=45.0)
    assert status_by_range(34.7, r) == "НИЖЕ"
    
    # Тест 5: Граничные значения
    r = Range(low=3.8, high=5.1)
    assert status_by_range(3.8, r) == "В НОРМЕ"  # на границе low
    assert status_by_range(5.1, r) == "В НОРМЕ"  # на границе high
    assert status_by_range(3.79, r) == "НИЖЕ"    # ниже границы
    assert status_by_range(5.11, r) == "ВЫШЕ"    # выше границы
    
    # Тест 6: NE = 6.34 при норме 1.80–7.70 → В НОРМЕ
    r = Range(low=1.8, high=7.7)
    assert status_by_range(6.34, r) == "В НОРМЕ"
    
    print("✓ status_by_range работает корректно")


def test_parse_items_from_candidates():
    """Тест парсинга кандидатов с реальными примерами"""
    candidates = """Скорость оседания	28	2-20	мм/ч
Гематокрит (HCT)	34.7	35.0-45.0	%
Эритроциты (RBC) 4.00 *10^	12	3.80-5.10	/л
Тромбоциты (PLT) 199 *10^	9	150-400	/л
Нейтрофилы: сегмент. (микроскопия)	73	47.0-72.0	%"""
    
    items = parse_items_from_candidates(candidates)
    assert len(items) > 0
    
    # Проверяем СОЭ
    esr = next((it for it in items if "соэ" in it.name.lower() or it.name == "ESR"), None)
    if esr:
        assert esr.value == 28.0
        assert esr.status == "ВЫШЕ"
        print(f"✓ СОЭ распознан: value={esr.value}, status={esr.status}")
    
    # Проверяем RBC
    rbc = next((it for it in items if it.name == "RBC"), None)
    if rbc:
        assert rbc.value == 4.0
        assert rbc.status == "В НОРМЕ"
        print(f"✓ RBC распознан: value={rbc.value}, status={rbc.status}")
    
    # Проверяем PLT
    plt = next((it for it in items if it.name == "PLT"), None)
    if plt:
        assert plt.value == 199.0
        assert plt.status == "В НОРМЕ"
        print(f"✓ PLT распознан: value={plt.value}, status={plt.status}")
    
    # Проверяем HCT
    hct = next((it for it in items if it.name == "HCT"), None)
    if hct:
        assert hct.value == 34.7
        assert hct.status == "НИЖЕ"
        print(f"✓ HCT распознан: value={hct.value}, status={hct.status}")
    
    print("✓ parse_items_from_candidates работает корректно")


def run_all_tests():
    """Запуск всех тестов"""
    print("Запуск тестов парсинга и статусов...\n")
    
    try:
        test_parse_float()
        test_parse_ref_range()
        test_status_by_range()
        test_parse_items_from_candidates()
        print("\n✅ Все тесты пройдены успешно!")
        return True
    except AssertionError as e:
        print(f"\n❌ Тест провален: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ Ошибка при выполнении тестов: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)


