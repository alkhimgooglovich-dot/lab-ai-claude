"""
Авто-валидатор для предотвращения регрессий.
Проверяет критичные функции парсинга и определения статусов.

Запуск: python test_validator.py
"""
import sys
import os
from pathlib import Path

# Исправление кодировки для Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем текущую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

try:
    from engine import (
        parse_float,
        parse_ref_range,
        status_by_range,
        Range,
        parse_items_from_candidates,
        helix_table_to_candidates,
        detect_panel,
        drop_percent_if_absolute,
    )
except ImportError as e:
    print(f"[ОШИБКА] Ошибка импорта: {e}")
    print("Убедитесь, что:")
    print("1. Виртуальное окружение активировано (venv\\Scripts\\activate)")
    print("2. Все зависимости установлены (pip install -r requirements.txt)")
    print("3. engine.py доступен в текущей директории")
    sys.exit(1)


def test_parse_float():
    """Тест парсинга чисел"""
    assert parse_float("4.00") == 4.0, "4.00 должен парситься как 4.0"
    assert parse_float("199") == 199.0, "199 должен парситься как 199.0"
    assert parse_float("28") == 28.0, "28 должен парситься как 28.0"
    assert parse_float("34.7") == 34.7, "34.7 должен парситься как 34.7"
    assert parse_float("0.02") == 0.02, "0.02 должен парситься как 0.02"
    return True


def test_parse_ref_range():
    """Тест парсинга референсных диапазонов"""
    # Обычные диапазоны
    r = parse_ref_range("3.80-5.10")
    assert r is not None, "Должен распарсить диапазон 3.80-5.10"
    assert r.low == 3.8, "low должен быть 3.8"
    assert r.high == 5.1, "high должен быть 5.1"
    
    r = parse_ref_range("150-400")
    assert r is not None, "Должен распарсить диапазон 150-400"
    assert r.low == 150.0, "low должен быть 150.0"
    assert r.high == 400.0, "high должен быть 400.0"
    
    r = parse_ref_range("2-20")
    assert r is not None, "Должен распарсить диапазон 2-20"
    assert r.low == 2.0, "low должен быть 2.0"
    assert r.high == 20.0, "high должен быть 20.0"
    
    # Защита от перепутанных low/high
    r = parse_ref_range("5.10-3.80")
    assert r is not None, "Должен распарсить диапазон 5.10-3.80"
    assert r.low == 3.8, "low должен быть исправлен на 3.8"
    assert r.high == 5.1, "high должен быть исправлен на 5.1"
    
    return True


def test_status_by_range():
    """Тест определения статусов - КРИТИЧНО для предотвращения регрессий"""
    # Тест 1: RBC = 4.00 при норме 3.80–5.10 → В НОРМЕ
    r = Range(low=3.8, high=5.1)
    status = status_by_range(4.00, r)
    assert status == "В НОРМЕ", f"RBC 4.00 при норме 3.80-5.10 должен быть В НОРМЕ, получен: {status}"
    
    # Тест 2: PLT = 199 при норме 150–400 → В НОРМЕ
    r = Range(low=150.0, high=400.0)
    status = status_by_range(199.0, r)
    assert status == "В НОРМЕ", f"PLT 199 при норме 150-400 должен быть В НОРМЕ, получен: {status}"
    
    # Тест 3: СОЭ = 28 при норме 2–20 → ВЫШЕ
    r = Range(low=2.0, high=20.0)
    status = status_by_range(28.0, r)
    assert status == "ВЫШЕ", f"СОЭ 28 при норме 2-20 должен быть ВЫШЕ, получен: {status}"
    
    # Тест 4: HCT = 34.7 при норме 35.0–45.0 → НИЖЕ
    r = Range(low=35.0, high=45.0)
    status = status_by_range(34.7, r)
    assert status == "НИЖЕ", f"HCT 34.7 при норме 35.0-45.0 должен быть НИЖЕ, получен: {status}"
    
    # Тест 5: Граничные значения
    r = Range(low=3.8, high=5.1)
    assert status_by_range(3.8, r) == "В НОРМЕ", "Значение на границе low должно быть В НОРМЕ"
    assert status_by_range(5.1, r) == "В НОРМЕ", "Значение на границе high должно быть В НОРМЕ"
    assert status_by_range(3.79, r) == "НИЖЕ", "Значение ниже границы должно быть НИЖЕ"
    assert status_by_range(5.11, r) == "ВЫШЕ", "Значение выше границы должно быть ВЫШЕ"
    
    # Тест 6: NE = 6.34 при норме 1.80–7.70 → В НОРМЕ
    r = Range(low=1.8, high=7.7)
    status = status_by_range(6.34, r)
    assert status == "В НОРМЕ", f"NE 6.34 при норме 1.80-7.70 должен быть В НОРМЕ, получен: {status}"
    
    return True


def test_parse_items_with_percentages():
    """Тест парсинга кандидатов с процентами лейкоформулы - КРИТИЧНО"""
    candidates = """Скорость оседания	28	2-20	мм/ч
Гематокрит (HCT)	34.7	35.0-45.0	%
Эритроциты (RBC) 4.00 *10^	12	3.80-5.10	/л
Тромбоциты (PLT) 199 *10^	9	150-400	/л
Нейтрофилы, % (NE%)	77	47.0-72.0	%
Лимфоциты, % (LY%)	18	19.0-37.0	%
Моноциты, % (MO%)	5	3.0-12.0	%
Эозинофилы, % (EO%)	0	1.0-5.0	%
Базофилы, % (BA%)	0	0.0-1.2	%
Нейтрофилы: сегмент. (микроскопия)	73	47.0-72.0	%"""
    
    items = parse_items_from_candidates(candidates)
    assert len(items) > 0, "Должны быть распарсены items"
    
    # Проверяем СОЭ
    esr = next((it for it in items if "соэ" in it.name.lower() or it.name == "ESR"), None)
    assert esr is not None, "СОЭ должен быть распознан"
    assert esr.value == 28.0, "СОЭ должен быть 28.0"
    assert esr.status == "ВЫШЕ", "СОЭ 28 при норме 2-20 должен быть ВЫШЕ"
    
    # Проверяем RBC
    rbc = next((it for it in items if it.name == "RBC"), None)
    assert rbc is not None, "RBC должен быть распознан"
    assert rbc.value == 4.0, "RBC должен быть 4.0"
    assert rbc.status == "В НОРМЕ", "RBC 4.00 при норме 3.80-5.10 должен быть В НОРМЕ"
    
    # Проверяем PLT
    plt = next((it for it in items if it.name == "PLT"), None)
    assert plt is not None, "PLT должен быть распознан"
    assert plt.value == 199.0, "PLT должен быть 199.0"
    assert plt.status == "В НОРМЕ", "PLT 199 при норме 150-400 должен быть В НОРМЕ"
    
    # КРИТИЧНО: Проверяем проценты лейкоформулы ДО и ПОСЛЕ drop_percent_if_absolute
    items_after_filter = drop_percent_if_absolute(items)
    
    ne_percent = next((it for it in items_after_filter if it.name == "NE%"), None)
    assert ne_percent is not None, "NE% должен быть распознан и НЕ удалён после фильтра"
    assert ne_percent.value == 77.0, "NE% должен быть 77.0"
    assert ne_percent.status == "ВЫШЕ", "NE% 77 при норме 47-72 должен быть ВЫШЕ"
    
    ly_percent = next((it for it in items_after_filter if it.name == "LY%"), None)
    assert ly_percent is not None, "LY% должен быть распознан и НЕ удалён после фильтра"
    assert ly_percent.value == 18.0, "LY% должен быть 18.0"
    assert ly_percent.status == "НИЖЕ", "LY% 18 при норме 19-37 должен быть НИЖЕ"
    
    eo_percent = next((it for it in items_after_filter if it.name == "EO%"), None)
    assert eo_percent is not None, "EO% должен быть распознан и НЕ удалён после фильтра"
    assert eo_percent.value == 0.0, "EO% должен быть 0.0"
    assert eo_percent.status == "НИЖЕ", "EO% 0 при норме 1-5 должен быть НИЖЕ"
    
    mo_percent = next((it for it in items_after_filter if it.name == "MO%"), None)
    assert mo_percent is not None, "MO% должен быть распознан"
    
    ba_percent = next((it for it in items_after_filter if it.name == "BA%"), None)
    assert ba_percent is not None, "BA% должен быть распознан"
    
    # Проверяем, что количество items не уменьшилось (проценты не удалены)
    assert len(items_after_filter) == len(items), f"Проценты не должны удаляться, было {len(items)}, стало {len(items_after_filter)}"
    
    return True


def test_helix_table_to_candidates_with_scientific_notation():
    """Тест обработки значений с *10^9/*10^12"""
    plain_text = """Лейкоциты (WBC)
8.23 *10^9/л
4.00 - 10.00

Эритроциты (RBC)
4.00 *10^12/л
3.80 - 5.10

Тромбоциты (PLT)
199 *10^9/л
150 - 400"""
    
    candidates = helix_table_to_candidates(plain_text)
    assert candidates, "Должны быть найдены кандидаты"
    
    items = parse_items_from_candidates(candidates)
    
    # Проверяем единицы измерения
    wbc = next((it for it in items if it.name == "WBC"), None)
    assert wbc is not None, "WBC должен быть распознан"
    assert "*10^9" in wbc.unit or "10^9" in wbc.unit, f"Единица WBC должна содержать *10^9, получено: {wbc.unit}"
    
    rbc = next((it for it in items if it.name == "RBC"), None)
    assert rbc is not None, "RBC должен быть распознан"
    assert "*10^12" in rbc.unit or "10^12" in rbc.unit, f"Единица RBC должна содержать *10^12, получено: {rbc.unit}"
    
    plt = next((it for it in items if it.name == "PLT"), None)
    assert plt is not None, "PLT должен быть распознан"
    assert "*10^9" in plt.unit or "10^9" in plt.unit, f"Единица PLT должна содержать *10^9, получено: {plt.unit}"
    
    return True


def test_detect_panel():
    """Тест определения типа панели анализов"""
    # Тест CBC
    cbc_names = {"WBC", "RBC", "HGB", "HCT", "PLT", "NE%", "LY%", "ESR"}
    scores = detect_panel(cbc_names)
    assert scores["cbc"] >= 3, "CBC должен быть обнаружен"
    assert scores["biochem"] < 3, "Биохимия не должна быть обнаружена для CBC"
    
    # Тест биохимии
    biochem_names = {"ALT", "AST", "TBIL", "CREA", "UREA", "GLUC"}
    scores = detect_panel(biochem_names)
    assert scores["biochem"] >= 3, "Биохимия должна быть обнаружена"
    assert scores["cbc"] < 3, "CBC не должна быть обнаружена для биохимии"
    
    # Тест липидограммы
    lipids_names = {"CHOL", "LDL", "HDL", "TRIG"}
    scores = detect_panel(lipids_names)
    assert scores["lipids"] >= 3, "Липидограмма должна быть обнаружена"
    
    # Тест смешанной панели
    mixed_names = {"WBC", "RBC", "ALT", "AST", "CHOL", "LDL"}
    scores = detect_panel(mixed_names)
    assert scores["cbc"] >= 2, "CBC должен быть частично обнаружен"
    assert scores["biochem"] >= 2, "Биохимия должна быть частично обнаружена"
    assert scores["lipids"] >= 2, "Липидограмма должна быть частично обнаружена"
    
    return True


def test_units_cleaning():
    """Тест очистки единиц от повторяющихся референсов"""
    # Симуляция случая с неправильной единицей "*10^9/л 0.02 - 0.50"
    candidates = """Эозинофилы (EO)	0	0.02-0.50	*10^9/л 0.02 - 0.50"""
    
    items = parse_items_from_candidates(candidates)
    assert len(items) > 0, "Должен быть распарсен хотя бы один item"
    
    eo = next((it for it in items if it.name == "EO"), None)
    assert eo is not None, "EO должен быть распознан"
    # Единица должна быть очищена от повторяющегося референса
    assert "0.02" not in eo.unit or eo.unit == "*10^9/л", f"Единица должна быть очищена, получено: '{eo.unit}'"
    
    return True


def test_complete_workflow():
    """Интеграционный тест полного workflow"""
    # Реальный пример из тестов
    candidates = """Скорость оседания	28	2-20	мм/ч
Гематокрит (HCT)	34.7	35.0-45.0	%
Распр. эрит. по V - коэф. вариац(RDW-CV)	15.2	11.6-14.8	%
Эозинофилы (EO)	0	0.02-0.50	*10^9/л
Нейтрофилы, % (NE%)	77	47.0-72.0	%
Лимфоциты, % (LY%)	18	19.0-37.0	%
Эозинофилы, % (EO%)	0	1.0-5.0	%
Нейтрофилы: сегмент. (микроскопия)	73	47.0-72.0	%
Лейкоциты (WBC)	8.23	4.00-10.00	*10^9/л
Эритроциты (RBC)	4.00	3.80-5.10	*10^12/л
Тромбоциты (PLT)	199	150-400	*10^9/л"""
    
    items = parse_items_from_candidates(candidates)
    assert len(items) >= 10, f"Должно быть распознано минимум 10 показателей, получено: {len(items)}"
    
    # Проверяем, что все проценты присутствуют
    percent_names = {"NE%", "LY%", "EO%"}
    found_percent_names = {it.name for it in items if it.name.endswith("%")}
    for name in percent_names:
        assert name in found_percent_names, f"{name} должен быть в результатах"
    
    # Проверяем отклонения
    high_low = [
        it for it in items
        if it.value is not None and it.ref is not None and it.status in ("ВЫШЕ", "НИЖЕ")
    ]
    
    # Должны быть найдены отклонения: СОЭ, HCT, RDW-CV, EO, NE%, LY%, EO%, NE_SEG
    assert len(high_low) >= 7, f"Должно быть найдено минимум 7 отклонений, получено: {len(high_low)}"
    
    # Проверяем конкретные отклонения
    deviation_names = {it.name for it in high_low}
    assert "ESR" in deviation_names, "СОЭ должен быть в отклонениях"
    assert "HCT" in deviation_names, "HCT должен быть в отклонениях"
    assert "NE%" in deviation_names, "NE% должен быть в отклонениях"
    assert "LY%" in deviation_names, "LY% должен быть в отклонениях"
    assert "EO%" in deviation_names, "EO% должен быть в отклонениях"
    
    return True


def run_all_tests():
    """Запуск всех тестов"""
    print("[ВАЛИДАТОР] Запуск авто-валидатора...\n")
    
    tests = [
        ("Парсинг чисел", test_parse_float),
        ("Парсинг референсных диапазонов", test_parse_ref_range),
        ("Определение статусов", test_status_by_range),
        ("Парсинг с процентами лейкоформулы", test_parse_items_with_percentages),
        ("Обработка *10^9/*10^12", test_helix_table_to_candidates_with_scientific_notation),
        ("Определение типа панели", test_detect_panel),
        ("Очистка единиц измерения", test_units_cleaning),
        ("Полный workflow", test_complete_workflow),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            print(f"[OK] {test_name}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {test_name}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {test_name}: неожиданная ошибка - {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"Результаты: [OK] {passed} пройдено, [FAIL] {failed} провалено")
    print(f"{'='*60}\n")
    
    if failed == 0:
        print("[УСПЕХ] Все тесты пройдены! Код готов к использованию.")
        return True
    else:
        print("[ВНИМАНИЕ] Обнаружены ошибки! Исправьте их перед использованием.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

