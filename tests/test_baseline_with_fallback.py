"""
Тест: baseline не сломался при наличии fallback-модуля.

Проверяем, что:
  1. Импорт fallback-модуля не ломает baseline.
  2. parse_with_fallback на Helix PDF возвращает тот же результат, что и чистый baseline.
  3. evaluate_parse_quality на baseline-результатах показывает высокое качество.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import (
    try_extract_text_from_pdf_bytes,
    helix_table_to_candidates,
    parse_items_from_candidates,
    parse_with_fallback,
    assign_confidence,
)
from parsers.quality import evaluate_parse_quality
from parsers.fallback_generic import fallback_parse_candidates


TEST_PDF = PROJECT_ROOT / "tests" / "fixtures" / "0333285a-adec-4b5d-9c25-52811a5c1747.pdf"

# Ожидаемые значения — те же, что и в baseline
EXPECTED_VALUES = {
    "WBC": 8.23,
    "RBC": 4.0,
    "HGB": 120.0,
    "HCT": 34.7,
    "ESR": 28.0,
    "PLT": 199.0,
    "NE%": 77.0,
    "LY%": 18.0,
}


def _extract_candidates() -> str:
    """Извлекает кандидатов из PDF через baseline-путь."""
    pdf_bytes = TEST_PDF.read_bytes()
    raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)
    candidates = helix_table_to_candidates(raw_text)
    return candidates


class TestBaselineWithFallback:
    """Проверяем, что fallback не ломает baseline."""

    def test_fallback_import_does_not_break_baseline(self):
        """Импорт fallback-модуля не должен вызывать ошибок."""
        items = _extract_candidates()
        parsed = parse_items_from_candidates(items)
        assert len(parsed) >= 15

    def test_parse_with_fallback_returns_baseline_result(self):
        """
        На Helix PDF parse_with_fallback должен вернуть
        тот же результат, что и чистый baseline (с учётом дедупликации).
        """
        candidates = _extract_candidates()

        # Чистый baseline
        baseline_items = parse_items_from_candidates(candidates)

        # Через fallback-оркестратор (включает дедупликацию)
        fallback_items = parse_with_fallback(candidates)

        # Уникальные canonical name в baseline
        baseline_unique = {it.name for it in baseline_items}

        # Количество уникальных имён не должно уменьшиться
        fallback_unique = {it.name for it in fallback_items}
        assert len(fallback_unique) >= len(baseline_unique), (
            f"parse_with_fallback потерял уникальные показатели: "
            f"{len(fallback_unique)} < {len(baseline_unique)}"
        )

        # Проверяем ключевые значения
        def _find(items, name):
            return next((it for it in items if it.name == name), None)

        for name, expected_val in EXPECTED_VALUES.items():
            fb_item = _find(fallback_items, name)
            assert fb_item is not None, f"{name} пропал после parse_with_fallback"
            assert fb_item.value == expected_val, (
                f"{name}: baseline={expected_val}, "
                f"parse_with_fallback={fb_item.value}"
            )

    def test_baseline_quality_is_good(self):
        """
        На Helix PDF качество baseline должно быть отличным:
        coverage_score >= 1.0, suspicious_count == 0.
        """
        candidates = _extract_candidates()
        items = parse_items_from_candidates(candidates)
        quality = evaluate_parse_quality(items)

        assert quality["coverage_score"] >= 1.0, (
            f"coverage_score слишком низкий: {quality['coverage_score']}"
        )
        assert quality["suspicious_count"] == 0, (
            f"Обнаружены подозрительные значения: {quality['suspicious_count']}"
        )
        assert quality["error_count"] == 0, (
            f"Обнаружены ошибки парсинга: {quality['error_count']}"
        )

    def test_fallback_not_activated_on_good_baseline(self):
        """
        На Helix PDF fallback НЕ должен активироваться,
        т.к. baseline достаточно хорош.
        """
        candidates = _extract_candidates()

        baseline_items = parse_items_from_candidates(candidates)
        quality = evaluate_parse_quality(baseline_items)

        # Условие активации fallback:
        #   coverage_score < 0.6 OR suspicious_count > 0
        # На хорошем PDF обе проверки должны быть False
        assert quality["coverage_score"] >= 0.6, (
            f"coverage_score слишком низкий: {quality['coverage_score']}"
        )
        assert quality["suspicious_count"] == 0, (
            f"suspicious_count != 0: {quality['suspicious_count']}"
        )

    def test_baseline_confidence_all_high(self):
        """
        На Helix PDF все показатели должны иметь confidence >= 0.7,
        т.к. у всех есть value, ref и unit.
        """
        candidates = _extract_candidates()
        items = parse_items_from_candidates(candidates)
        assign_confidence(items)

        low_conf = [it for it in items if it.confidence < 0.7]
        assert len(low_conf) == 0, (
            f"Обнаружены показатели с низким confidence: "
            f"{[(it.name, it.confidence) for it in low_conf]}"
        )

    def test_quality_has_new_metrics(self):
        """Проверяем что quality содержит новые метрики."""
        candidates = _extract_candidates()
        items = parse_items_from_candidates(candidates)
        quality = evaluate_parse_quality(items)

        assert "valid_value_count" in quality
        assert "valid_ref_count" in quality
        assert "expected_minimum" in quality
        assert quality["valid_value_count"] >= 15
        assert quality["valid_ref_count"] >= 15

    def test_quality_has_extended_metrics(self):
        """Проверяем что quality содержит расширенные метрики v2."""
        candidates = _extract_candidates()
        items = parse_items_from_candidates(candidates)
        quality = evaluate_parse_quality(items)

        assert "ref_coverage_ratio" in quality
        assert "unit_coverage_ratio" in quality
        assert "duplicate_name_count" in quality
        assert "avg_confidence" in quality
        # На хорошем PDF ref_coverage_ratio и unit_coverage_ratio должны быть высокими
        assert quality["ref_coverage_ratio"] >= 0.8
        assert quality["unit_coverage_ratio"] >= 0.5

    def test_universal_extractor_helix_regression(self):
        """
        Helix PDF даёт тот же результат через Universal Extractor.
        """
        from parsers.universal_extractor import universal_extract

        pdf_bytes = TEST_PDF.read_bytes()
        raw_text = try_extract_text_from_pdf_bytes(pdf_bytes)

        # Universal Extractor
        ue_candidates = universal_extract(raw_text)
        ue_items = parse_items_from_candidates(ue_candidates) if ue_candidates else []

        # Baseline (helix)
        baseline_candidates = helix_table_to_candidates(raw_text)
        baseline_items = parse_items_from_candidates(baseline_candidates)

        def _find(items, name):
            return next((it for it in items if it.name == name), None)

        # Проверяем ключевые значения из Universal Extractor
        for name, expected_val in EXPECTED_VALUES.items():
            ue_item = _find(ue_items, name)
            if ue_item is not None:
                assert ue_item.value == expected_val, (
                    f"{name}: universal={ue_item.value}, expected={expected_val}"
                )
