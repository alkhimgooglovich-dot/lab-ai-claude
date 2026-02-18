"""
Тесты для фильтрации шапочных / служебных строк.

Проверяем:
  - is_header_service_line() корректно распознаёт «мусор из шапки»
  - is_noise() фильтрует эти строки
  - Строки с биомаркерами НЕ фильтруются (no false positive)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from parsers.line_scorer import is_noise, is_header_service_line


class TestHeaderServiceLineFiltering:
    """Шапочные / служебные строки НЕ должны проходить в кандидаты."""

    # --- Должны фильтроваться (is_noise → True) ---

    def test_phone_plus7(self):
        assert is_noise("+7 (495) 123-45-67")

    def test_phone_8800(self):
        assert is_noise("8-800-200-36-30")

    def test_email(self):
        assert is_noise("info@helix.ru")

    def test_url_www(self):
        assert is_noise("www.helix.ru")

    def test_url_https(self):
        assert is_noise("https://www.invitro.ru/results")

    def test_inn(self):
        assert is_noise("ИНН 7701234567")

    def test_ogrn(self):
        assert is_noise("ОГРН 1027739654321")

    def test_kpp(self):
        assert is_noise("КПП 770101001")

    def test_address(self):
        assert is_noise("г. Москва, ул. Профсоюзная, д. 15, корп. 2")

    def test_order_number_hash(self):
        assert is_noise("№ 00123456789")

    def test_barcode_digits(self):
        assert is_noise("4607038490123")  # 13+ цифр — EAN штрихкод

    def test_date_only(self):
        assert is_noise("01.01.2025 12:30:00")

    def test_fio_format(self):
        assert is_noise("Иванов И.И.")

    def test_patient_line(self):
        # "пациент:" уже есть в _NOISE_PREFIXES
        assert is_noise("Пациент: Сидоров Пётр Александрович")

    # --- Прямые проверки is_header_service_line ---

    def test_header_phone_direct(self):
        assert is_header_service_line("+7 (495) 123-45-67")

    def test_header_email_direct(self):
        assert is_header_service_line("info@helix.ru")

    def test_header_url_direct(self):
        assert is_header_service_line("www.helix.ru")

    def test_header_inn_direct(self):
        assert is_header_service_line("ИНН 7701234567")

    def test_header_ogrn_direct(self):
        assert is_header_service_line("ОГРН 1027739654321")

    def test_header_kpp_direct(self):
        assert is_header_service_line("КПП 770101001")

    def test_header_address_direct(self):
        assert is_header_service_line("г. Москва, ул. Профсоюзная, д. 15")

    def test_header_address_keyword(self):
        assert is_header_service_line("Адрес: г. Москва, ул. Ленина, д. 5")

    def test_header_order_number_direct(self):
        assert is_header_service_line("№ 00123456789")

    def test_header_barcode_direct(self):
        assert is_header_service_line("4607038490123")

    def test_header_fio_direct(self):
        assert is_header_service_line("Иванов И.И.")

    def test_header_date_iso(self):
        assert is_header_service_line("2025-01-15")

    def test_header_date_ru(self):
        assert is_header_service_line("01.01.2025 12:30:00")

    # --- НЕ должны фильтроваться (is_noise → False) ---

    def test_wbc_line_not_noise(self):
        assert not is_noise("Лейкоциты (WBC) 8.23 *10^9/л 4.00 - 10.00")

    def test_esr_line_not_noise(self):
        assert not is_noise("Скорость оседания 28 мм/ч 2 - 20")

    def test_hemoglobin_not_noise(self):
        assert not is_noise("Гемоглобин (HGB) 145 г/л 130 - 160")

    def test_crp_not_noise(self):
        assert not is_noise("C-реактивный белок (CRP) 2.5 мг/л <=5.0")

    def test_rbc_with_ref_not_noise(self):
        assert not is_noise("Эритроциты (RBC) 4.5 *10^12/л 4.0 - 5.5")

    def test_plt_not_noise(self):
        assert not is_noise("Тромбоциты (PLT) 250 *10^9/л 150 - 400")

    # --- is_header_service_line НЕ ловит биомаркеры ---

    def test_header_wbc_not_flagged(self):
        assert not is_header_service_line("Лейкоциты (WBC) 8.23 *10^9/л 4.00 - 10.00")

    def test_header_hemoglobin_not_flagged(self):
        assert not is_header_service_line("Гемоглобин (HGB) 145 г/л 130 - 160")

    def test_header_esr_not_flagged(self):
        assert not is_header_service_line("Скорость оседания 28 мм/ч 2 - 20")

    def test_header_empty_not_flagged(self):
        """Пустые строки не обрабатываются is_header_service_line (обрабатывает is_noise)."""
        assert not is_header_service_line("")

    def test_header_short_number_not_flagged(self):
        """Короткие цифровые строки (< 13 цифр) не считаются штрихкодами."""
        assert not is_header_service_line("123456")


