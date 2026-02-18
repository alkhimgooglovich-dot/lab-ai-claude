"""
Детектор формата лаборатории.

detect_lab_format(raw_text) → 'medsi' | 'helix' | 'generic'

Логика:
  - МЕДСИ: определяется через parsers.medsi_extractor.is_medsi_format
  - Helix: двухстрочные пары «имя» → «число + единица + ref»
  - generic: всё остальное
"""

import re


def detect_lab_format(raw_text: str) -> str:
    """
    Определяет формат лаборатории по тексту.

    Возвращает:
        'medsi'   — бланк МЕДСИ (inline ref+value)
        'helix'   — бланк Helix / InVitro (двухстрочный)
        'generic' — неизвестный / любой другой
    """
    if not raw_text:
        return "generic"

    # ─── МЕДСИ ───
    from parsers.medsi_extractor import is_medsi_format
    if is_medsi_format(raw_text):
        return "medsi"

    # ─── Helix / InVitro ───
    # Признаки: заголовки с табуляциями, или двухстрочные пары
    lines = raw_text.splitlines()

    # Табуляции Helix: "Исследование\tРезультат" / "Тест\tРезультат"
    for line in lines[:20]:
        if re.search(r"(Исследование|Тест)\s*\t\s*Результат", line):
            return "helix"

    # Helix-двухстрочный: строка-имя (буквы) → строка-значение (число)
    helix_pair_count = 0
    for i in range(len(lines) - 1):
        name_line = lines[i].strip()
        val_line = lines[i + 1].strip()
        if (
            name_line
            and re.search(r"[A-Za-zА-Яа-я]{3,}", name_line)
            and not re.match(r"^\d", name_line)
            and val_line
            and re.match(r"^[↑↓+]?\s*\d", val_line)
        ):
            helix_pair_count += 1
    if helix_pair_count >= 5:
        return "helix"

    return "generic"



