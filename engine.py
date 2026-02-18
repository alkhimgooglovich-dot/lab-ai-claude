# engine.py — ВСТАВЬ ЦЕЛИКОМ (полная замена файла)
# Фиксы:
# - PDF multi-page: объединение pypdf (если есть) + OCR async
# - возвращена обработка изображений (OCR sync)
# - извлечение показателей: двухстрочный + однострочный парсер
# - корректное определение отклонений для блока "Итог по фактам"
# - фильтр мусора (SGS/заказы/служебные строки)
# - логи: outputs/ocr_debug.txt

import re
import base64
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List, Set, Dict, Any
from uuid import uuid4

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ==========================
# ПАПКИ / ФАЙЛЫ
# ==========================
OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = Path("templates")
TEMPLATE_NAME = "report.html"

RAW_RESPONSE_PATH = OUT_DIR / "yc_raw_response.json"

OCR_RAW_PATH = OUT_DIR / "ocr_raw.json"
OCR_PLAIN_PATH = OUT_DIR / "ocr_plain.txt"
OCR_CANDIDATES_PATH = OUT_DIR / "ocr_candidates.txt"

OCR_HTTP_LAST_PATH = OUT_DIR / "ocr_http_last.txt"
OCR_POLL_LOG_PATH = OUT_DIR / "ocr_poll_log.txt"
OCR_DEBUG_PATH = OUT_DIR / "ocr_debug.txt"

PDF_TEXT_EXTRACT_PATH = OUT_DIR / "pdf_text_extract.txt"


# ==========================
# КЛЮЧ СЕРВИСНОГО АККАУНТА
# ==========================
SERVICE_ACCOUNT_KEY_PATH = Path("Key") / "authorized_key.json"
IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
IAM_JWT_AUD = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
IAM_JWT_ALG = "PS256"


# ==========================
# UX / Пороги подсветки
# ==========================
WARN_PCT = 10.0


# ==========================
# НАСТРОЙКИ YandexGPT
# ==========================
FOLDER_ID = "b1ghp3lahbvv6gmcofq9"
MODEL_URI = f"gpt://{FOLDER_ID}/yandexgpt/latest"
API_URL_LLM = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

TEMPERATURE = 0.2
MAX_TOKENS = 1300
TIMEOUT_SEC = 120

SYSTEM_PROMPT = (
    "Ты — медицинский информационный помощник по лабораторным анализам.\n"
    "ЗАПРЕЩЕНО: ставить диагноз; назначать лечение; рекомендовать лекарства/дозировки.\n"
    "РАЗРЕШЕНО: объяснять показатели; отмечать отклонения; подсказать, что обсудить с врачом; "
    "каких специалистов имеет смысл обсудить/посетить; какие обследования можно обсудить.\n"
    "Стиль: спокойно, нейтрально. Формулировки: "
    "«может быть связано», «имеет смысл обсудить», «при необходимости».\n"
    "Опираться строго на ФАКТЫ ниже. Если данных мало — скажи, что вывод ограничен."
)


# ==========================
# НАСТРОЙКИ Vision OCR
# ==========================
OCR_API_BASE = "https://ocr.api.cloud.yandex.net/ocr/v1"
OCR_TIMEOUT_SEC = 180
OCR_MODEL = "page"
OCR_LANGS = ["*"]

OCR_PDF_OPERATION_WAIT_SEC = 180   # чтобы не висеть бесконечно
OCR_GET_RECOGNITION_WAIT_SEC = 180
OPERATIONS_API_BASE = "https://operation.api.cloud.yandex.net/operations"


# ==========================
# Справочники (локальные)
# ==========================
EXPLAIN_DICT = {
    "ALT":  "ALT — фермент, часто используемый как индикатор состояния клеток печени и желчных путей.",
    "AST":  "AST — фермент; обычно интерпретируется вместе с ALT и клиническими данными.",
    "TBIL": "TBIL — билирубин общий; показатель обмена билирубина.",
    "DBIL": "DBIL — билирубин прямой; показатель фракции билирубина.",
    "CHOL": "CHOL — общий холестерин: показатель липидного обмена; обычно оценивается вместе с LDL/HDL/ТГ и факторами риска.",
    "LDL":  "LDL — «условно нежелательная» фракция холестерина; оценивают в контексте общего сердечно-сосудистого риска.",
    "HDL":  "HDL — «защитная» фракция холестерина; интерпретируется вместе с другими липидами.",
    "TRIG": "TRIG — триглицериды; показатель липидного обмена.",
    "CREA": "CREA — креатинин: показатель для ориентировочной оценки функции почек (обычно вместе с расчётной СКФ).",
    "UREA": "UREA — мочевина: показатель белкового обмена; часто оценивается вместе с креатинином.",
    "CRP":  "CRP — C-реактивный белок: маркёр воспаления (неспецифичный), интерпретируется вместе с симптомами и другими данными.",
    "GLUC": "GLUC — глюкоза: показатель углеводного обмена; интерпретация зависит от условий сдачи и повторных измерений.",
    "ESR":  "СОЭ — показатель, который может повышаться при воспалительных процессах и ряде других состояний; всегда оценивается вместе с симптомами и другими анализами.",
    "NE_SEG": "Нейтрофилы (сегментоядерные, микроскопия) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
    "NE%": "Нейтрофилы (процент) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
    "LY%": "Лимфоциты (процент) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
    "MO%": "Моноциты (процент) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
    "EO%": "Эозинофилы (процент) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
    "BA%": "Базофилы (процент) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
    "EO": "Эозинофилы (абсолютное значение) — часть лейкоформулы; оценка зависит от клиники и других показателей крови.",
}

SPECIALIST_MAP = {
    "ALT": {"терапевт", "гастроэнтеролог"},
    "AST": {"терапевт", "гастроэнтеролог"},
    "TBIL": {"терапевт", "гастроэнтеролог"},
    "DBIL": {"терапевт", "гастроэнтеролог"},
    "CHOL": {"терапевт", "кардиолог"},
    "LDL": {"терапевт", "кардиолог"},
    "HDL": {"терапевт", "кардиолог"},
    "TRIG": {"терапевт", "кардиолог"},
    "CREA": {"терапевт", "нефролог"},
    "UREA": {"терапевт", "нефролог"},
    "CRP": {"терапевт"},
    "GLUC": {"терапевт", "эндокринолог"},
    "ESR": {"терапевт"},
    "NE_SEG": {"терапевт"},
}


# ============================================================
# helpers
# ============================================================
def _dbg(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prev = OCR_DEBUG_PATH.read_text(encoding="utf-8") if OCR_DEBUG_PATH.exists() else ""
    OCR_DEBUG_PATH.write_text(prev + f"[{ts}] {msg}\n", encoding="utf-8")


def _safe_json_loads(text: str) -> Any:
    s = (text or "").lstrip()
    dec = json.JSONDecoder()
    obj, _idx = dec.raw_decode(s)
    return obj


def _resp_json_or_die(r: requests.Response, where: str) -> Any:
    try:
        return _safe_json_loads(r.text)
    except Exception:
        OCR_HTTP_LAST_PATH.write_text(
            f"[{where}] HTTP {r.status_code}\n\n{r.text[:200000]}",
            encoding="utf-8",
        )
        raise


def _log_poll(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prev = OCR_POLL_LOG_PATH.read_text(encoding="utf-8") if OCR_POLL_LOG_PATH.exists() else ""
    OCR_POLL_LOG_PATH.write_text(prev + f"[{ts}] {msg}\n", encoding="utf-8")


def _dedup_lines_keep_order(lines: List[str]) -> List[str]:
    seen = set()
    out = []
    for ln in lines:
        k = re.sub(r"\s+", " ", ln.strip())
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(ln)
    return out


# ============================================================
# IAM TOKEN PROVIDER (JWT -> IAM token) + CACHE
# ============================================================
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _load_sa_key() -> Dict[str, Any]:
    if not SERVICE_ACCOUNT_KEY_PATH.exists():
        raise FileNotFoundError(f"Не найден ключ: {SERVICE_ACCOUNT_KEY_PATH.resolve()}")
    return json.loads(SERVICE_ACCOUNT_KEY_PATH.read_text(encoding="utf-8"))


def _normalize_private_key(pem: str) -> str:
    return pem.replace("\\n", "\n").strip() + "\n"


def _sign_ps256(private_key_pem: str, message: bytes) -> bytes:
    private_key = serialization.load_pem_private_key(
        _normalize_private_key(private_key_pem).encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return signature


def _make_jwt_for_iam(sa_key: Dict[str, Any]) -> str:
    kid = sa_key.get("id") or sa_key.get("key_id")
    sa_id = sa_key.get("service_account_id")
    private_key = sa_key.get("private_key")

    if not kid or not sa_id or not private_key:
        raise ValueError("В authorized_key.json должны быть поля: service_account_id, private_key и (id или key_id)")

    now = int(time.time())
    exp = now + 3600

    header = {"typ": "JWT", "alg": IAM_JWT_ALG, "kid": kid}
    payload = {"iss": sa_id, "aud": IAM_JWT_AUD, "iat": now, "exp": exp}

    header_b64 = _b64url(json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = _sign_ps256(private_key, signing_input)
    sig_b64 = _b64url(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


class IamTokenProvider:
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._expires_at_ts: float = 0.0

    def get(self) -> str:
        if self._token and time.time() < (self._expires_at_ts - 120):
            return self._token

        sa_key = _load_sa_key()
        jwt_token = _make_jwt_for_iam(sa_key)

        # Повторные попытки при сетевых ошибках
        last_err = None
        for attempt in range(3):
            try:
                r = requests.post(IAM_TOKEN_URL, json={"jwt": jwt_token}, timeout=30)
                if r.status_code != 200:
                    raise RuntimeError(f"IAM token error HTTP {r.status_code}: {r.text[:1200]}")

                data = _resp_json_or_die(r, "iam/v1/tokens")
                iam_token = data.get("iamToken")
                expires_at = data.get("expiresAt")
                if not iam_token or not expires_at:
                    raise RuntimeError(f"Неожиданный ответ IAM: {data}")

                expires_at = expires_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(expires_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                self._expires_at_ts = dt.timestamp()
                self._token = iam_token
                return iam_token

            except requests.exceptions.ConnectionError as e:
                last_err = f"Ошибка подключения к Yandex Cloud IAM API: {str(e)}. Проверьте интернет-соединение и доступность iam.api.cloud.yandex.net"
                if attempt < 2:
                    time.sleep(1 + attempt)  # Задержка перед повторной попыткой
                    continue
            except requests.exceptions.Timeout as e:
                last_err = f"Таймаут при подключении к Yandex Cloud IAM API: {str(e)}"
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
            except requests.exceptions.RequestException as e:
                last_err = f"Ошибка сети при запросе IAM токена: {str(e)}"
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise RuntimeError(f"Не удалось получить IAM токен после 3 попыток. {last_err}")

        raise RuntimeError(f"Не удалось получить IAM токен. {last_err}")


_IAM = IamTokenProvider()


def get_iam_token() -> str:
    return _IAM.get()


# ==========================
# ПАРСИНГ
# ==========================
@dataclass
class Range:
    low: Optional[float]
    high: Optional[float]


@dataclass
class Item:
    raw_name: str
    name: str
    value: Optional[float]
    unit: str
    ref_text: str
    ref: Optional[Range]
    ref_source: str
    status: str
    confidence: float = 0.0   # 0..1, вычисляется после парсинга


# ==========================
# CONFIDENCE
# ==========================
def compute_item_confidence(it: Item) -> float:
    """
    Расчёт confidence для одного показателя:
      1.0 — value + ref + unit + известный биомаркер
      0.9 — value + ref + unit (без проверки биомаркера)
      0.8 — value + ref + известный биомаркер (без unit)
      0.7 — value + ref, без unit и биомаркера
      0.5 — value валидное, но ref отсутствует
      0.3 — value есть, но raw_name подозрительный (короткий / мусорный)
      0.0 — value подозрительное / None
    """
    if it.value is None:
        return 0.0

    # Подозрительное значение → 0.0
    raw = it.raw_name or ""
    if any(ch in raw for ch in ['^', '*', '/']):
        import re as _re
        if not _re.search(r"\*10\^\d+", raw):
            return 0.0

    has_ref = it.ref is not None
    has_unit = bool((it.unit or "").strip())

    # Проверяем, является ли имя известным биомаркером
    from parsers.line_scorer import has_known_biomarker
    is_known = has_known_biomarker(it.raw_name or it.name)

    if has_ref and has_unit and is_known:
        return 1.0
    if has_ref and has_unit:
        return 0.9
    if has_ref and is_known:
        return 0.8
    if has_ref:
        return 0.7
    if is_known:
        return 0.5

    # value есть, но ни ref, ни биомаркер не определены
    name_clean = (it.raw_name or "").strip()
    if len(name_clean) < 3 or not re.search(r"[A-Za-zА-Яа-я]{2,}", name_clean):
        return 0.3

    return 0.5


def assign_confidence(items: List[Item]) -> None:
    """Вычисляет и записывает confidence для каждого Item (in-place)."""
    for it in items:
        it.confidence = compute_item_confidence(it)


ALIASES = {
    "ALT": "ALT", "AST": "AST",
    "TBIL": "TBIL", "DBIL": "DBIL",
    "TRIG": "TRIG", "TG": "TRIG",
    "CHOL": "CHOL", "HDL": "HDL", "LDL": "LDL",
    "UREA": "UREA", "CREA": "CREA",
    "CRPN": "CRP", "CRP": "CRP",
    "GLUC": "GLUC", "GLU": "GLUC",
    "WBC": "WBC", "RBC": "RBC", "HGB": "HGB", "HCT": "HCT",
    "MCV": "MCV", "MCH": "MCH", "MCHC": "MCHC",
    "RDW-SD": "RDW-SD", "RDW-CV": "RDW-CV",
    "PLT": "PLT", "PDW": "PDW", "MPV": "MPV", "P-LCR": "P-LCR",
    "NE": "NE", "LY": "LY", "MO": "MO", "EO": "EO", "BA": "BA",
    "NE%": "NE%", "LY%": "LY%", "MO%": "MO%", "EO%": "EO%", "BA%": "BA%",
    "ESR": "ESR",
}

RUS_NAME_MAP = {
    "скорость оседания": "ESR",
    "соэ": "ESR",
    "лейкоцит": "WBC",
    "эритроцит": "RBC",
    "гемоглоб": "HGB",
    "гематокрит": "HCT",
    "средний объем эритроцита": "MCV",
    "средн. сод. гемоглобина": "MCH",
    "средн. конц. гемоглобина": "MCHC",
    "rdw-sd": "RDW-SD",
    "rdw-cv": "RDW-CV",
    "тромбоцит": "PLT",
    "pdw": "PDW",
    "mpv": "MPV",
    "p-lcr": "P-LCR",
    "нейтрофилы: сегмент": "NE_SEG",          # ВАЖНО: микроскопия
    "нейтрофилы сегмент": "NE_SEG",
    "нейтрофилы: палочк": "NE_STAB",          # палочкоядерные (микроскопия)
    "нейтрофилы палочк": "NE_STAB",
    "нейтрофил": "NE",
    "лимфоцит": "LY",
    "моноцит": "MO",
    "эозинофил": "EO",
    "базофил": "BA",
    # Проценты - различные варианты написания
    "нейтрофилы, %": "NE%",
    "нейтрофилы %": "NE%",
    "нейтрофилы (%)": "NE%",
    "нейтрофилы(процент)": "NE%",
    "лимфоциты, %": "LY%",
    "лимфоциты %": "LY%",
    "лимфоциты (%)": "LY%",
    "лимфоциты(процент)": "LY%",
    "моноциты, %": "MO%",
    "моноциты %": "MO%",
    "моноциты (%)": "MO%",
    "моноциты(процент)": "MO%",
    "эозинофилы, %": "EO%",
    "эозинофилы %": "EO%",
    "эозинофилы (%)": "EO%",
    "эозинофилы(процент)": "EO%",
    "базофилы, %": "BA%",
    "базофилы %": "BA%",
    "базофилы (%)": "BA%",
    "базофилы(процент)": "BA%",
}


def clean_raw_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    # убираем лишние пометки, но оставляем смысл
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)     # всё в скобках (WBC), (микроскопия) и т.п.
    s = s.replace("%", "%")                  # оставим % в raw_name (для отображения), но нормализация ниже
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_name(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").strip())

    # коды в скобках (если они были в исходном raw_name до clean_raw_name)
    m = re.search(r"\(([A-Za-z]{2,6}%?)\)", s)
    if m:
        code = m.group(1).upper()
        return ALIASES.get(code, code)

    low = s.lower()
    for k, v in RUS_NAME_MAP.items():
        if k in low:
            return v

    # попытка вытащить "NE%" из текста
    m2 = re.search(r"\b([A-Za-z]{2,6}%?)\b", s)
    if m2:
        code = m2.group(1).upper()
        if code in ALIASES:
            return ALIASES[code]

    return s.replace(" ", "_").replace("-", "_").upper()


def parse_float(x: str) -> Optional[float]:
    x = (x or "").strip().replace(",", ".")
    x = re.sub(r"[^\d\.\-]", "", x)
    try:
        return float(x)
    except Exception:
        return None


def parse_ref_range(text: str) -> Optional[Range]:
    """
    Парсит референсный диапазон из текста.
    Поддерживает: "3.80-5.10", "150-400", "<=20", ">=5.0", "до 5"
    """
    t = (text or "").strip()
    if not t:
        return None
    t = t.replace("—", "-").replace("–", "-").replace(",", ".")

    # Канонизация «до X» → «<X» (до удаления пробелов!)
    m_do = re.match(r"^[Дд]о\s*(\d+(?:\.\d+)?)$", t)
    if m_do:
        t = f"<{m_do.group(1)}"

    # Удаляем пробелы, но оставляем дефис между числами
    t = re.sub(r"\s+", "", t)
    
    # Проверяем на сравнения <=, >=, <, >
    m = re.match(r"^(<=|<|≤)(-?\d+(?:\.\d+)?)$", t)
    if m:
        return Range(low=None, high=float(m.group(2)))

    m = re.match(r"^(>=|>|≥)(-?\d+(?:\.\d+)?)$", t)
    if m:
        return Range(low=float(m.group(2)), high=None)

    # Проверяем диапазон вида "low-high"
    m = re.match(r"^(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)$", t)
    if m:
        low_val = float(m.group(1))
        high_val = float(m.group(2))
        # Защита от перепутанных low/high
        if low_val > high_val:
            _dbg(f"WARN: parse_ref_range low > high: {t}, меняем местами")
            return Range(low=high_val, high=low_val)
        return Range(low=low_val, high=high_val)

    return None


def status_by_range(value: Optional[float], r: Optional[Range]) -> str:
    """
    Определяет статус значения относительно референсного диапазона.
    Важно: проверяем сначала НИЖЕ, потом ВЫШЕ, иначе граничные значения могут быть неправильно классифицированы.
    """
    if value is None:
        return "НЕ РАСПОЗНАНО"
    if r is None:
        return "НЕИЗВЕСТНО"
    
    # Проверяем нижнюю границу (строго меньше)
    if r.low is not None and value < r.low:
        return "НИЖЕ"
    
    # Проверяем верхнюю границу (строго больше)
    if r.high is not None and value > r.high:
        return "ВЫШЕ"
    
    # Если обе границы определены и значение внутри (включая границы) — В НОРМЕ
    if r.low is not None and r.high is not None:
        if r.low <= value <= r.high:
            return "В НОРМЕ"
    
    # Если только одна граница определена и значение в пределах
    if r.low is not None and r.high is None and value >= r.low:
        return "В НОРМЕ"
    if r.low is None and r.high is not None and value <= r.high:
        return "В НОРМЕ"
    
    return "В НОРМЕ"


def format_range(r: Optional[Range]) -> str:
    if r is None:
        return "—"
    if r.low is None and r.high is not None:
        return f"< {r.high}"
    if r.low is not None and r.high is None:
        return f"> {r.low}"
    return f"{r.low}–{r.high}"


# ============================================================
# Helix: сборщик кандидатов
# ============================================================
def _extract_ref_text(s: str) -> str:
    t = (s or "").strip().replace("—", "-").replace("–", "-").replace(",", ".")
    t = re.sub(r"\s+", " ", t)

    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    m = re.search(r"(<=|>=|<|>|≤|≥)\s*(\d+(?:\.\d+)?)", t)
    if m:
        op = m.group(1).replace("≤", "<=").replace("≥", ">=")
        return f"{op}{m.group(2)}"

    # Формат «до число» → «<число»
    m = re.search(r"(?:^|\s)[Дд]о\s*(\d+(?:\.\d+)?)", t)
    if m:
        return f"<{m.group(1)}"

    return ""


def _starts_like_value_line(s: str) -> bool:
    t = (s or "").strip()
    return bool(re.match(r"^(?:[↑↓+]\s*)?\d", t))


def _is_noise_line(low: str) -> bool:
    """Делегирует проверку в is_noise() из line_scorer (единый источник правды)."""
    from parsers.line_scorer import is_noise
    return is_noise(low)


def _looks_like_name_line(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return False
    low = t.lower()
    if _is_noise_line(low):
        return False
    if _starts_like_value_line(t):
        return False
    # должно быть хотя бы 2 буквы
    if not re.search(r"[A-Za-zА-Яа-я]{2,}", t):
        return False
    return True


def _normalize_scientific_notation(s: str) -> str:
    """
    Нормализует варианты записи степени:
    10^9, 10~9, 10⁹, 109 → 10^9
    """
    # Unicode степени → обычные цифры с ^
    s = s.replace("¹", "^1").replace("²", "^2").replace("³", "^3")
    s = s.replace("⁴", "^4").replace("⁵", "^5").replace("⁶", "^6")
    s = s.replace("⁷", "^7").replace("⁸", "^8").replace("⁹", "^9").replace("⁰", "^0")
    # Варианты записи: 10~9, 10*9 → 10^9 (без -, чтобы не ломать рефы типа "10 - 40")
    s = re.sub(r"10\s*[~*]\s*(\d+)", r"10^\1", s, flags=re.IGNORECASE)
    # Если уже есть 10^N - оставляем как есть
    return s


def _parse_value_unit_from_line(s: str) -> Tuple[Optional[float], str]:
    """
    Парсит значение и единицу из строки.
    Поддерживает форматы:
    - "8.23 *10^9/л" -> (8.23, "*10^9/л")
    - "199 *10^9 /л" -> (199.0, "*10^9/л")
    - "28 мм/ч" -> (28.0, "мм/ч")
    - "77.0 %" -> (77.0, "%")
    """
    t = re.sub(r"\s+", " ", (s or "").strip())
    t = t.replace("↑", "").replace("↓", "").replace("+", "").strip()
    
    # Нормализуем научную нотацию
    t = _normalize_scientific_notation(t)
    
    # Сначала пытаемся найти формат *10^N или 10^N (с пробелами или без)
    # Варианты: "*10^9/л", "* 10^9 /л", "10^9/л"
    pow_patterns = [
        r"([-+]?\d+(?:[.,]\d+)?)\s*\*\s*10\s*\^\s*(\d+)(.*)$",  # 8.23 *10^9/л
        r"([-+]?\d+(?:[.,]\d+)?)\s+10\s*\^\s*(\d+)(.*)$",       # 8.23 10^9/л
    ]
    
    for pattern in pow_patterns:
        pow_match = re.search(pattern, t, re.IGNORECASE)
        if pow_match:
            base = parse_float(pow_match.group(1))
            if base is not None:
                exp = pow_match.group(2)
                rest = pow_match.group(3).strip() if len(pow_match.groups()) > 2 else ""
                # Формируем единицу: *10^N + остаток (например, "/л")
                unit = f"*10^{exp}"
                if rest:
                    # Если есть остаток (/л, /л и т.д.), добавляем его
                    unit = f"{unit}{rest}".strip()
                else:
                    # Если остатка нет, проверяем, что было после 10^N
                    after_match_end = pow_match.end()
                    if after_match_end < len(t):
                        after_part = t[after_match_end:].strip()
                        if after_part and not re.match(r"^\d", after_part):
                            # Это не число, скорее всего единица
                            unit = f"{unit}{after_part}".strip()
                return base, unit
    
    # Обычный формат: число + единица (без степени)
    m = re.match(r"^([-+]?\d+(?:[.,]\d+)?)\s*(.*)$", t)
    if not m:
        return None, ""
    val = parse_float(m.group(1))
    rest = (m.group(2) or "").strip()
    # Берём первую "часть" единицы (до пробела или до конца)
    # Но сохраняем %, мм/ч, г/л целиком
    if rest:
        # Если есть / или %, берём до следующего пробела или до конца
        unit_match = re.match(r"^([^/\s]+(?:[/%][^/\s]*)?)", rest)
        if unit_match:
            unit = unit_match.group(1).strip()
        else:
            unit = rest.split(" ")[0].strip()
    else:
        unit = ""
    return val, unit


def _try_parse_one_line_row(line: str) -> Optional[str]:
    """
    Однострочный формат:
      "Скорость оседания 28 2-20 мм/ч"
      "Нейтрофилы: сегмент. (микроскопия) 73.0 % 47.0 - 72.0"
      "NE% 77.0 % 47.0 - 72.0"
    Возвращает: name\tvalue\tref\tunit
    """
    s = re.sub(r"\s+", " ", (line or "").strip())
    if not s:
        return None
    low = s.lower()
    if _is_noise_line(low):
        return None
    if _starts_like_value_line(s):
        return None

    # найдём референс (span) прямо в строке
    range_match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*[–—-]\s*(-?\d+(?:[.,]\d+)?)", s)
    comp_match = re.search(r"(<=|>=|<|>|≤|≥)\s*(-?\d+(?:[.,]\d+)?)", s)

    ref_span = None
    ref_text = ""

    if range_match:
        a = range_match.group(1).replace(",", ".")
        b = range_match.group(2).replace(",", ".")
        ref_text = f"{a}-{b}"
        ref_span = range_match.span()
    elif comp_match:
        op = comp_match.group(1).replace("≤", "<=").replace("≥", ">=")
        x = comp_match.group(2).replace(",", ".")
        ref_text = f"{op}{x}"
        ref_span = comp_match.span()
    else:
        return None

    left = s[:ref_span[0]].strip()
    right = s[ref_span[1]:].strip()

    # значение — последнее число в left (или число перед *10^N)
    left_norm = left.replace(",", ".")
    left_norm = _normalize_scientific_notation(left_norm)  # Нормализуем научную нотацию
    
    # Сначала проверяем формат *10^N или 10^N
    pow_patterns = [
        r"([-+]?\d+(?:[.,]\d+)?)\s*\*\s*10\s*\^\s*(\d+)",  # 8.23 *10^9
        r"([-+]?\d+(?:[.,]\d+)?)\s+10\s*\^\s*(\d+)",       # 8.23 10^9
    ]
    
    pow_match = None
    for pattern in pow_patterns:
        pow_match = re.search(pattern, left_norm, re.IGNORECASE)
        if pow_match:
            break
    
    if pow_match:
        value_str = pow_match.group(1).replace(",", ".")
        value = parse_float(value_str)
        if value is None:
            return None
        exp = pow_match.group(2)
        # Имя — всё до числа перед *10^
        name_part = left_norm[:pow_match.start()].strip()
        # Единица: *10^N + возможный остаток (например, "/л")
        after_exp = left_norm[pow_match.end():].strip()
        if after_exp:
            # Если после 10^N есть текст (например, "/л"), добавляем его
            unit = f"*10^{exp}{after_exp}".strip()
        else:
            # Или ищем единицу в right части
            unit = f"*10^{exp}"
            if right:
                right_unit = right.split(" ")[0].strip()
                if right_unit:
                    unit = f"{unit}{right_unit}"
    else:
        # Обычный формат: берём последнее число
        nums = re.findall(r"[-+]?\d+(?:\.\d+)?", left_norm)
        if not nums:
            return None
        value_str = nums[-1]
        value = parse_float(value_str)
        if value is None:
            return None
        name_part = left_norm.rsplit(value_str, 1)[0].strip()
        # unit: чаще всего после value в left (например "73.0 %") или в right
        unit = ""
        # Ищем единицу после числа в left
        after_value = left_norm.split(value_str, 1)[1] if value_str in left_norm else ""
        if after_value:
            after_value = after_value.strip()
            # Берём первую часть (до пробела или до конца), сохраняя / и %
            unit_match = re.match(r"^([^/\s]+(?:[/%][^/\s]*)?)", after_value)
            if unit_match:
                unit = unit_match.group(1).strip()
        if not unit and right:
            unit = right.split(" ")[0].strip()
    
    if not name_part or not re.search(r"[A-Za-zА-Яа-я]", name_part):
        return None

    return f"{name_part}\t{value:g}\t{ref_text}\t{unit}".strip()


def helix_table_to_candidates(plain_text: str) -> str:
    """
    ДВА прохода:
    - pass1 (двухстрочный): name_line -> value/ref_line (чтобы не терялась СОЭ и др.)
    - pass2 (однострочный): ловим строки микроскопии и проценты
    
    Обрабатывает все страницы PDF - игнорирует маркеры страниц (--- PAGE N ---), если они есть.
    """
    lines = [re.sub(r"\s+", " ", l.strip()) for l in (plain_text or "").splitlines()]
    # Убираем маркеры страниц (если они остались после ocr_result_to_plaintext)
    lines = [l for l in lines if l and not re.match(r"^---\s*PAGE\s+\d+\s+---", l, re.IGNORECASE)]
    lines = [l for l in lines if l]
    _dbg(f"helix_table_to_candidates: input_lines={len(lines)} (после удаления маркеров страниц)")

    out: List[str] = []

    # pass1: двухстрочный
    pending_name: Optional[str] = None
    i = 0
    while i < len(lines):
        l = lines[i]
        low = l.lower()

        if _is_noise_line(low):
            i += 1
            continue

        if _looks_like_name_line(l):
            pending_name = l
            i += 1
            continue

        if pending_name and _starts_like_value_line(l):
            # Объединяем текущую строку и следующую (если есть), чтобы поймать *10^N
            combined_line = l
            if i + 1 < len(lines) and re.search(r"^\s*\d+\s", lines[i + 1]):
                # Следующая строка начинается с числа — возможно продолжение *10^N
                combined_line = f"{l} {lines[i + 1]}"
            
            val, unit = _parse_value_unit_from_line(combined_line)
            if val is None:
                # Если значение не распознано, сбрасываем pending_name и пробуем дальше
                pending_name = None
                i += 1
                continue

            ref = _extract_ref_text(combined_line)
            adv = 1
            if not ref and i + 1 < len(lines):
                # Референс может быть в следующей строке
                next_line = lines[i + 1] if i + 1 < len(lines) else ""
                ref2 = _extract_ref_text(next_line)
                if ref2:
                    ref = ref2
                    adv = 2

            if ref:
                candidate = f"{pending_name}\t{val:g}\t{ref}\t{unit}".strip()
                out.append(candidate)
                _dbg(f"candidate (2-line): {pending_name[:40]}... val={val} ref={ref} unit={unit}")
                pending_name = None
                i += adv
                continue
            else:
                # Референс не найден — сбрасываем pending_name
                _dbg(f"WARN: no ref for {pending_name[:40]}... value_line={l[:50]}")
                pending_name = None
                i += 1
                continue

        # Если pending_name есть, но текущая строка не подходит — сбрасываем
        if pending_name:
            pending_name = None
        i += 1

    # pass2: однострочный
    out2: List[str] = []
    for l in lines:
        cand = _try_parse_one_line_row(l)
        if cand:
            out2.append(cand)
            _dbg(f"candidate (1-line): {cand[:60]}...")

    merged = _dedup_lines_keep_order(out + out2)
    _dbg(f"helix_table_to_candidates: output_lines={len(merged)} (2-line={len(out)}, 1-line={len(out2)})")
    return "\n".join(merged).strip()


def _smart_to_candidates(raw_text: str) -> str:
    """
    Авто-детект формата лаборатории и преобразование в TSV-кандидаты.

    Порядок:
      1. МЕДСИ — специальная обработка (склейки ref+value).
      2. Universal Extractor — для всех остальных.
      3. Fallback: старый helix (на случай регрессии).
    """
    from parsers.medsi_extractor import is_medsi_format, medsi_inline_to_candidates
    from parsers.universal_extractor import universal_extract

    # МЕДСИ — специальная обработка (склейки ref+value)
    if is_medsi_format(raw_text):
        _dbg("_smart_to_candidates: detected MEDSI format")
        candidates = medsi_inline_to_candidates(raw_text)
        if candidates:
            _dbg(f"_smart_to_candidates: MEDSI → {len(candidates.splitlines())} candidates")
            return candidates
        _dbg("_smart_to_candidates: MEDSI extractor empty, falling back")

    # Universal Extractor — для всех остальных
    candidates = universal_extract(raw_text)
    if candidates:
        _dbg(f"_smart_to_candidates: Universal → {len(candidates.splitlines())} candidates")
        return candidates

    # Fallback: старый helix (на случай регрессии)
    _dbg("_smart_to_candidates: Universal empty, falling back to helix")
    return helix_table_to_candidates(raw_text)


def parse_items_from_candidates(raw_text: str) -> List[Item]:
    """
    Поддерживаем:
      1) name\tvalue\tref\tunit
      2) name\tvalue\tref unit
      3) name\tvalue unit\tref
      4) name value *10^N\t... (исправление разбитых значений)
    """
    items: List[Item] = []

    def _split_ref_and_unit(ref_text: str) -> tuple[str, str]:
        t = (ref_text or "").strip()
        if not t:
            return "", ""
        t_norm = t.replace("—", "-").replace("–", "-")
        t_norm = re.sub(r"\s+", " ", t_norm).strip()
        m = re.match(r"^(.+?)(?:\s+)([A-Za-zА-Яа-яµ/%\.\-]+)$", t_norm)
        if not m:
            return t, ""
        left = m.group(1).strip()
        unit = m.group(2).strip()

        left_check = left.replace(",", ".").replace(" ", "")
        left_check = left_check.replace("≤", "<=").replace("≥", ">=")

        if re.match(r"^(-?\d+(\.\d+)?)-(-?\d+(\.\d+)?)$", left_check) or re.match(r"^(<=|>=|<|>)(-?\d+(\.\d+)?)$", left_check):
            return left, unit

        return t, ""

    def _split_value_and_unit(val_text: str) -> tuple[str, str]:
        t = re.sub(r"\s+", " ", (val_text or "").strip())
        if not t:
            return "", ""
        m = re.match(r"^([-+]?\d+(?:[.,]\d+)?)(?:\s+)([A-Za-zА-Яа-яµ/%\.\-]+)$", t)
        if not m:
            return t, ""
        return m.group(1), m.group(2)

    def _fix_broken_scientific_notation(raw_name: str, raw_val: str) -> tuple[str, str]:
        """
        Исправляет случаи, когда значение разбито:
        raw_name = "Лейкоциты (WBC) 8.23 *10^"
        raw_val = "9"
        Возвращает: ("Лейкоциты (WBC)", "8.23")
        """
        # Проверяем, есть ли в raw_name паттерн "*10^"
        pow_match = re.search(r"([-+]?\d+(?:[.,]\d+)?)\s*\*\s*10\s*\^", raw_name, re.IGNORECASE)
        if pow_match:
            # raw_val может быть степенью (цифра) или уже корректным значением
            raw_val_stripped = raw_val.strip()
            # Извлекаем число перед *10^
            base_str = pow_match.group(1).replace(",", ".")
            base_val = parse_float(base_str)
            if base_val is not None:
                # Удаляем из raw_name всё от числа до конца
                name_clean = raw_name[:pow_match.start()].strip()
                # Если raw_val - это цифра (степень), игнорируем её, берём base_str
                # Если raw_val - это уже значение, оставляем его
                if raw_val_stripped.isdigit() and len(raw_val_stripped) <= 2:
                    # Скорее всего это степень, игнорируем
                    return name_clean, base_str
                else:
                    # Возможно, это уже значение
                    val_check = parse_float(raw_val_stripped)
                    if val_check is not None:
                        return name_clean, raw_val_stripped
                    return name_clean, base_str
        return raw_name, raw_val

    for line in (raw_text or "").splitlines():
        if not line.strip():
            continue

        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3:
            continue

        raw_name = parts[0].strip()
        raw_val = parts[1].strip()
        ref_text = parts[2].strip()
        unit = parts[3].strip() if len(parts) >= 4 else ""

        # Исправление разбитых значений с *10^
        raw_name, raw_val = _fix_broken_scientific_notation(raw_name, raw_val)

        # если unit прилип к value
        if not unit:
            raw_val2, unit2 = _split_value_and_unit(raw_val)
            if unit2:
                raw_val = raw_val2
                unit = unit2

        # если unit прилип к ref
        if not unit:
            ref2, unit2 = _split_ref_and_unit(ref_text)
            if unit2:
                ref_text = ref2
                unit = unit2
        
        # Очистка единицы от повторяющихся референсов (например, "*10^9/л 0.02 - 0.50" -> "*10^9/л")
        if unit:
            # Удаляем из единицы паттерны, похожие на референсы (числа с дефисом или диапазоны)
            unit_cleaned = re.sub(r"\s+\d+\.?\d*\s*[-–—]\s*\d+\.?\d*", "", unit).strip()
            # Если единица стала пустой или слишком короткой, оставляем оригинал
            if unit_cleaned and len(unit_cleaned) >= 2:
                unit = unit_cleaned

        raw_name_cleaned = clean_raw_name(raw_name)
        name = normalize_name(raw_name)
        if name == raw_name.replace(" ", "_").replace("-", "_").upper():
            # если нормализация не дала смысла — попробуем по cleaned
            name = normalize_name(raw_name_cleaned)

        value = parse_float(raw_val)
        ref = parse_ref_range(ref_text) if ref_text else None
        status = status_by_range(value, ref)
        ref_source = "референс лаборатории" if ref else "нет"

        # Логирование проблемных случаев
        if value is not None and ref is not None:
            if status == "ВЫШЕ" and value <= ref.high if ref.high else False:
                _dbg(f"WARN: {name} value={value} ref={format_range(ref)} status={status} (возможно ошибка)")
            if status == "НИЖЕ" and value >= ref.low if ref.low else False:
                _dbg(f"WARN: {name} value={value} ref={format_range(ref)} status={status} (возможно ошибка)")

        items.append(Item(
            raw_name=raw_name,
            name=name,
            value=value,
            unit=unit,
            ref_text=ref_text,
            ref=ref,
            ref_source=ref_source,
            status=status,
        ))

    return items


def parse_with_fallback(raw_text: str) -> List[Item]:
    """
    Архитектура "baseline-first + safe-fallback":

    1. Всегда сначала запускаем baseline-парсер (parse_items_from_candidates).
    2. Оцениваем качество результатов через evaluate_parse_quality.
    3. Если (coverage_score < 0.6) ИЛИ (suspicious_count > 0):
       → запускаем fallback_generic
       → выбираем результат по приоритетам.
    4. Иначе используем baseline как есть.

    Приоритеты сравнения (п.5 задачи):
      1) suspicious_count == 0  (приоритет — чистота)
      2) max valid_value_count  (больше распознанных)
      3) max valid_ref_count    (больше референсов)

    ВАЖНО: baseline-логика НЕ изменяется. Fallback — отдельный модуль.
    """
    from parsers.quality import evaluate_parse_quality
    from parsers.fallback_generic import fallback_parse_candidates

    # --- ШАГ 1: baseline ---
    baseline_items = parse_items_from_candidates(raw_text) if "\t" in raw_text else []
    if not baseline_items:
        # Baseline ничего не дал — пробуем fallback
        _dbg("parse_with_fallback: baseline returned 0 items, trying fallback")
        fallback_items = fallback_parse_candidates(raw_text)
        if fallback_items:
            _dbg(f"parse_with_fallback: fallback returned {len(fallback_items)} items")
            return fallback_items
        return baseline_items  # пустой список

    # --- ШАГ 1.5: дедупликация baseline ---
    assign_confidence(baseline_items)
    baseline_items, _ = deduplicate_items(baseline_items)

    # --- ШАГ 2: оцениваем качество baseline ---
    baseline_quality = evaluate_parse_quality(baseline_items)
    _dbg(f"parse_with_fallback: baseline quality={baseline_quality}")

    needs_fallback = (
        baseline_quality["coverage_score"] < 0.6
        or baseline_quality["suspicious_count"] > 0
    )

    if not needs_fallback:
        # Baseline достаточно хорош — возвращаем его
        _dbg("parse_with_fallback: baseline OK, no fallback needed")
        return baseline_items

    # --- ШАГ 3: fallback ---
    _dbg("parse_with_fallback: baseline insufficient, running fallback")
    fallback_items = fallback_parse_candidates(raw_text)

    if not fallback_items:
        _dbg("parse_with_fallback: fallback returned 0 items, using baseline")
        return baseline_items

    fallback_quality = evaluate_parse_quality(fallback_items)
    _dbg(f"parse_with_fallback: fallback quality={fallback_quality}")

    # --- ШАГ 4: выбираем лучший по приоритетам ---
    def _rank(q: dict) -> tuple:
        """
        Кортеж для сравнения (больше = лучше):
          1) suspicious == 0 → True (1) предпочтительнее False (0)
          2) valid_value_count — больше = лучше
          3) valid_ref_count — больше = лучше
        """
        return (
            1 if q["suspicious_count"] == 0 else 0,
            q["valid_value_count"],
            q["valid_ref_count"],
        )

    baseline_rank = _rank(baseline_quality)
    fallback_rank = _rank(fallback_quality)

    if fallback_rank > baseline_rank:
        _dbg(f"parse_with_fallback: fallback wins (rank {fallback_rank} > {baseline_rank})")
        return fallback_items
    else:
        _dbg(f"parse_with_fallback: baseline wins (rank {baseline_rank} >= {fallback_rank})")
        return baseline_items


def detect_panel(parsed_names: Set[str]) -> Dict[str, int]:
    """
    Определяет тип панели анализов по наличию маркеров.
    Возвращает словарь с оценками для каждой панели.
    
    Args:
        parsed_names: множество нормализованных имён показателей
        
    Returns:
        словарь с ключами "cbc", "biochem", "lipids" и значениями (количество найденных маркеров)
    """
    cbc_markers = {"WBC", "RBC", "HGB", "HCT", "PLT", "NE%", "LY%", "MO%", "EO%", "BA%", "NE", "LY", "MO", "EO", "BA", "ESR", "NE_SEG"}
    biochem_markers = {"ALT", "AST", "TBIL", "DBIL", "CREA", "UREA", "GLUC", "CRP"}
    lipids_markers = {"CHOL", "LDL", "HDL", "TRIG"}
    
    cbc_score = len(parsed_names & cbc_markers)
    biochem_score = len(parsed_names & biochem_markers)
    lipids_score = len(parsed_names & lipids_markers)
    
    return {
        "cbc": cbc_score,
        "biochem": biochem_score,
        "lipids": lipids_score,
    }


def deduplicate_items(items: List[Item]) -> List[Item]:
    """
    Дедупликация по canonical name (item.name).
    Из дублей выбираем лучший по скорингу:
      1) confidence (выше — лучше)
      2) наличие ref (ref is not None — лучше)
      3) наличие unit (unit непустой — лучше)
    Остальные отбрасываем.

    Возвращает (deduplicated_items, dropped_count).
    """
    from collections import defaultdict
    groups: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        groups[it.name].append(it)

    result: List[Item] = []
    dropped = 0
    for name, group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue
        # Сортируем: лучший первый
        group.sort(key=lambda it: (
            getattr(it, 'confidence', 0.0),
            1 if it.ref is not None else 0,
            1 if (it.unit or '').strip() else 0,
        ), reverse=True)
        result.append(group[0])
        dropped += len(group) - 1
    return result, dropped


def apply_sanity_filter(items: List[Item]) -> tuple[List[Item], int]:
    """
    Применяет sanity-фильтр к списку Item.

    - Для известных canonical показателей: выбрасывает очевидный OCR-мусор.
    - Для неизвестных: оставляет как есть.

    Returns:
        (filtered_items, outlier_count)
    """
    from parsers.sanity_ranges import is_sanity_outlier

    kept = []
    outlier_count = 0
    for it in items:
        if it.value is not None and is_sanity_outlier(it.name, it.value):
            _dbg(f"sanity_outlier: {it.name}={it.value} → отброшен")
            outlier_count += 1
        else:
            kept.append(it)
    return kept, outlier_count


def drop_percent_if_absolute(items: List[Item]) -> List[Item]:
    """
    ОТКЛЮЧЕНО: для лейкоформулы проценты и абсолютные значения - это разные показатели,
    оба должны отображаться. Функция возвращает все items без изменений.
    """
    # Возвращаем все items - проценты не удаляем, так как они важны для анализа
    return items


def build_dict_explanations(high_low: List[Item]) -> str:
    if not high_low:
        return "Нет отклонений — пояснения не требуются."
    lines = []
    for it in high_low:
        lines.append(f"- {it.name}: {EXPLAIN_DICT.get(it.name, '(нет справки — можно добавить)')}")
    return "\n".join(lines)


def suggest_specialists(high_low: List[Item]) -> List[str]:
    specs: Set[str] = set()
    for it in high_low:
        specs |= SPECIALIST_MAP.get(it.name, set())
    if high_low:
        specs.add("терапевт")
    order = ["терапевт", "кардиолог", "гастроэнтеролог", "эндокринолог", "нефролог"]
    return sorted(specs, key=lambda x: (order.index(x) if x in order else 999, x))


# ==========================
# LLM call (ретраи)
# ==========================
def call_yandexgpt(iam_token: str, user_text: str) -> str:
    payload = {
        "modelUri": MODEL_URI,
        "completionOptions": {"stream": False, "temperature": TEMPERATURE, "maxTokens": str(MAX_TOKENS)},
        "messages": [
            {"role": "system", "text": SYSTEM_PROMPT},
            {"role": "user", "text": user_text},
        ],
    }
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }

    last_err = None
    for delay in (1, 2, 4):
        r = requests.post(API_URL_LLM, headers=headers, json=payload, timeout=TIMEOUT_SEC)
        RAW_RESPONSE_PATH.write_text(r.text, encoding="utf-8")

        if r.status_code == 200:
            data = _resp_json_or_die(r, "foundationModels/v1/completion")
            return data["result"]["alternatives"][0]["message"]["text"]

        if r.status_code in (500, 502, 503, 504):
            last_err = f"LLM HTTP {r.status_code}: {r.text[:800]}"
            time.sleep(delay)
            continue

        raise RuntimeError(f"LLM HTTP {r.status_code}. См. {RAW_RESPONSE_PATH}\n{r.text[:1200]}")

    raise RuntimeError(f"LLM временно недоступен после ретраев. Последняя ошибка: {last_err}")


def build_llm_prompt(sex: str, age: int, high_low: List[Item], dict_expl: str, specialist_list: List[str]) -> str:
    if not high_low:
        deviations = "Отклонений по распознанным референсам нет."
    else:
        deviations = "\n".join(
            [
                f"- {it.raw_name}: {it.status} | значение {it.value:g} {it.unit or ''} | норма {it.ref_text or format_range(it.ref)}"
                for it in high_low
                if it.value is not None and it.ref is not None
            ]
        )

    specialist_hint = ", ".join(specialist_list) if specialist_list else "—"

    return f"""Пациент: пол {sex}, возраст {age}.

ФАКТЫ (СТРОГО по отклонениям):
{deviations}

Короткие справки (словарь, без ИИ):
{dict_expl}

Подсказка по специалистам (ориентир, НЕ диагноз):
{specialist_hint}

Сформируй итоговый ответ СТРОГО с заголовками:
ДИСКЛЕЙМЕР
КРАТКИЙ ИТОГ ПО ФАКТАМ
ЧТО ЭТО МОЖЕТ ОЗНАЧАТЬ
ВАЖНО ПОНИМАТЬ
К КАКИМ СПЕЦИАЛИСТАМ ИМЕЕТ СМЫСЛ ОБРАТИТЬСЯ
ЧТО ИМЕЕТ СМЫСЛ ОБСУДИТЬ С ВРАЧОМ
ВОПРОСЫ ВРАЧУ
СРОЧНОСТЬ
""".strip()


def build_fallback_text(sex: str, age: int, items: List[Item], high_low: List[Item]) -> str:
    disclaimer = (
        "ДИСКЛЕЙМЕР\n"
        "Отчёт носит справочный характер, не является диагнозом и не заменяет консультацию врача.\n"
        "Лечение и лекарства не назначаются.\n"
    )

    if not items:
        return disclaimer + "\nКРАТКИЙ ИТОГ ПО ФАКТАМ\nНе удалось распознать показатели.\n"

    if not high_low:
        return disclaimer + (
            "\nКРАТКИЙ ИТОГ ПО ФАКТАМ\n"
            "По распознанным референсам отклонений не обнаружено.\n"
            "\nЧТО ИМЕЕТ СМЫСЛ ОБСУДИТЬ С ВРАЧОМ\n"
            "• Уточнить, все ли показатели и референсы корректно распознаны.\n"
        )

    lines = []
    for it in high_low:
        lines.append(f"• {it.raw_name}: {it.status} — {it.value:g} {it.unit or ''} (норма: {it.ref_text})")

    specs = suggest_specialists(high_low)
    spec_line = ", ".join(specs) if specs else "терапевт"

    return (
        disclaimer
        + "\nКРАТКИЙ ИТОГ ПО ФАКТАМ\n"
        + "\n".join(lines)
        + "\n\nК КАКИМ СПЕЦИАЛИСТАМ ИМЕЕТ СМЫСЛ ОБРАТИТЬСЯ\n"
        + f"• {spec_line}\n"
        + "\nВОПРОСЫ ВРАЧУ\n"
        + "• Какие отклонения наиболее значимы с учётом симптомов и анамнеза?\n"
        + "• Нужен ли контроль/пересдача и когда?\n"
        + "• Какие дополнительные обследования имеет смысл обсудить?\n"
    )


# ==========================
# HTML render
# ==========================
def status_class_for_item(it: Item, warn_pct: float = WARN_PCT) -> str:
    if it.value is None or it.ref is None:
        return "muted"
    if it.status == "В НОРМЕ":
        return "status-normal"

    r = it.ref
    v = it.value

    if it.status == "ВЫШЕ":
        if r.high is not None and r.high != 0:
            pct = (v - r.high) / r.high * 100.0
            return "status-warn" if pct <= warn_pct else "status-high"
        return "status-high"

    if it.status == "НИЖЕ":
        if r.low is not None and r.low != 0:
            pct = (r.low - v) / r.low * 100.0
            return "status-warn" if pct <= warn_pct else "status-high"
        return "status-high"

    return "muted"


def build_template_context(sex: str, age: int, items: List[Item], high_low: List[Item], human_text: str, missing_warnings: Optional[List[str]] = None) -> dict:
    """
    Формирует контекст для шаблона отчёта.
    high_low — список отклонений (ВЫШЕ/НИЖЕ) для блока "Краткий итог по фактам".
    missing_warnings — список предупреждений о неполноте данных.
    """
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Формируем facts для блока "Краткий итог по фактам"
    facts: List[str] = []
    for it in high_low:
        code = it.raw_name
        status_lower = it.status.lower()
        src = it.ref_source
        facts.append(f"<span class='mono'>{code}</span> — <strong>{status_lower}</strong> референса (источник: {src})")
    
    rows = []
    for it in items:
        value_str = "" if it.value is None else f"{it.value:g}"
        rows.append({
            "code": it.raw_name,
            "value": value_str,
            "unit": it.unit or "",
            "ref_text": it.ref_text or (format_range(it.ref) if it.ref else ""),
            "ref_source": it.ref_source,
            "status": it.status,
            "status_class": status_class_for_item(it, WARN_PCT),
        })
    
    # Формируем пояснения из словаря
    explain_lines: List[str] = []
    for it in high_low:
        expl = EXPLAIN_DICT.get(it.name)
        if expl:
            explain_lines.append(f"<strong class='mono'>{it.name}</strong>: {expl}")
    
    return {
        "sex": sex,
        "age": age,
        "created_at": created_at,
        "facts": facts,
        "rows": rows,
        "explain_lines": explain_lines,
        "human_text": human_text,
        "raw_path": str(RAW_RESPONSE_PATH),
        "missing_warnings": missing_warnings or [],
    }


def render_html_report(context: dict) -> str:
    tpl_path = TEMPLATES_DIR / TEMPLATE_NAME
    if not tpl_path.exists():
        raise FileNotFoundError(f"Не найден шаблон: {tpl_path.resolve()}")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(TEMPLATE_NAME)
    return template.render(**context)


# ==========================
# PDF: HTML -> PDF
# ==========================
def render_pdf_from_html(html_path: Path, pdf_path: Path, created_at: str) -> None:
    header_template = """
    <div style="font-size:9px; width:100%; padding:0 12mm; color:#666;">
      <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
        <span>Информационный отчёт</span>
        <span>Не является диагнозом</span>
      </div>
    </div>
    """

    footer_template = f"""
    <div style="font-size:9px; width:100%; padding:0 12mm; color:#666;">
      <div style="display:flex; justify-content:space-between; align-items:center; width:100%;">
        <span>Дата/время: {created_at}</span>
        <span>Стр. <span class="pageNumber"></span> / <span class="totalPages"></span></span>
      </div>
    </div>
    """

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template=header_template,
            footer_template=footer_template,
            margin={"top": "18mm", "right": "12mm", "bottom": "18mm", "left": "12mm"},
        )
        browser.close()


# ==========================
# Vision OCR
# ==========================
def _ocr_headers(iam_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {iam_token}",
        "x-folder-id": FOLDER_ID,
        "Content-Type": "application/json",
    }


def _op_headers(iam_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json",
    }


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def ocr_image_sync(iam_token: str, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    payload = {"mimeType": mime_type, "languageCodes": OCR_LANGS, "model": OCR_MODEL, "content": _b64(file_bytes)}
    url = f"{OCR_API_BASE}/recognizeText"
    r = requests.post(url, headers=_ocr_headers(iam_token), data=json.dumps(payload), timeout=OCR_TIMEOUT_SEC)
    _dbg(f"OCR image sync HTTP {r.status_code} mime={mime_type}")
    if r.status_code != 200:
        raise RuntimeError(f"OCR image error HTTP {r.status_code}: {r.text[:1200]}")
    return _resp_json_or_die(r, "ocr/recognizeText")


def ocr_pdf_async_start(iam_token: str, pdf_bytes: bytes) -> str:
    payload = {"mimeType": "application/pdf", "languageCodes": OCR_LANGS, "model": OCR_MODEL, "content": _b64(pdf_bytes)}
    url = f"{OCR_API_BASE}/recognizeTextAsync"
    r = requests.post(url, headers=_ocr_headers(iam_token), data=json.dumps(payload), timeout=OCR_TIMEOUT_SEC)
    _dbg(f"OCR pdf async start HTTP {r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"OCR PDF start error HTTP {r.status_code}: {r.text[:1200]}")
    data = _resp_json_or_die(r, "ocr/recognizeTextAsync")
    op_id = data.get("id") or data.get("operationId")
    if not op_id:
        raise RuntimeError(f"OCR PDF: не найден operationId в ответе: {data}")
    return op_id


def operations_get(iam_token: str, operation_id: str) -> Dict[str, Any]:
    url = f"{OPERATIONS_API_BASE}/{operation_id}"
    r = requests.get(url, headers=_op_headers(iam_token), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Operation.Get error HTTP {r.status_code}: {r.text[:1200]}")
    return _resp_json_or_die(r, "operation/get")


def _is_not_ready_404(text: str) -> bool:
    t = (text or "").lower()
    return ("not ready" in t) or ("operation data is not ready" in t)


def ocr_pdf_get_recognition(iam_token: str, operation_id: str) -> Dict[str, Any]:
    url = f"{OCR_API_BASE}/getRecognition"
    r = requests.get(url, headers=_ocr_headers(iam_token), params={"operationId": operation_id}, timeout=OCR_TIMEOUT_SEC)
    _dbg(f"OCR getRecognition HTTP {r.status_code}")
    if r.status_code == 404 and _is_not_ready_404(r.text):
        return {"_not_ready": True, "_raw": r.text}
    if r.status_code != 200:
        raise RuntimeError(f"OCR getRecognition error HTTP {r.status_code}: {r.text[:1200]}")
    return _resp_json_or_die(r, "ocr/getRecognition")


def _collect_text_annotations(node: Any, out_texts: List[str]) -> None:
    if node is None:
        return

    if isinstance(node, dict):
        ft = node.get("fullText")
        if isinstance(ft, str) and ft.strip():
            out_texts.append(ft.strip())

        blocks = node.get("blocks")
        if isinstance(blocks, list):
            for b in blocks:
                if isinstance(b, dict):
                    lines = b.get("lines")
                    if isinstance(lines, list):
                        for ln in lines:
                            if isinstance(ln, dict):
                                t = ln.get("text")
                                if isinstance(t, str) and t.strip():
                                    out_texts.append(t.strip())

        for v in node.values():
            if isinstance(v, (dict, list)):
                _collect_text_annotations(v, out_texts)

    elif isinstance(node, list):
        for it in node:
            _collect_text_annotations(it, out_texts)


def ocr_result_to_plaintext(ocr_json: Dict[str, Any]) -> str:
    """
    Извлекает текст из OCR результата, объединяя все страницы.
    Возвращает единый текст без маркеров страниц для упрощения парсинга.
    """
    texts: List[str] = []
    page_texts_list: List[str] = []  # Для логирования

    result = ocr_json.get("result")
    if isinstance(result, dict):
        pages = None
        if isinstance(result.get("pages"), list):
            pages = result.get("pages")
        elif isinstance(result.get("results"), list):
            pages = result.get("results")

        if isinstance(pages, list) and pages:
            _dbg(f"OCR result: found {len(pages)} pages")
            for idx, page in enumerate(pages, start=1):
                page_texts: List[str] = []
                _collect_text_annotations(page, page_texts)
                page_text = "\n".join([t for t in page_texts if t]).strip()
                if page_text:
                    page_texts_list.append(page_text)
                    texts.append(page_text)
                    # Логируем первые 200 символов каждой страницы для отладки
                    _dbg(f"  PAGE {idx}: len={len(page_text)}, preview={page_text[:200]}...")
        else:
            _collect_text_annotations(result, texts)

    if not texts:
        _collect_text_annotations(ocr_json, texts)

    # Объединяем все страницы в единый текст (без маркеров страниц)
    full_text = "\n".join(texts).strip()
    
    # уберём дубли (построчно)
    lines = full_text.splitlines()
    cleaned_lines: List[str] = []
    prev = None
    for line in lines:
        line_stripped = line.strip()
        if line_stripped and line_stripped != prev:
            cleaned_lines.append(line)
            prev = line_stripped
    
    result_text = "\n".join(cleaned_lines).strip()
    _dbg(f"ocr_result_to_plaintext: pages={len(page_texts_list)}, total_lines={len(result_text.splitlines())}, total_len={len(result_text)}")
    return result_text


# ==========================
# PDF direct text (быстрый путь)
# ==========================
def try_extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Извлекает текст из PDF через pypdf, объединяя все страницы.
    Не обязательно: если pypdf нет — просто вернёт "".
    """
    try:
        from pypdf import PdfReader  # type: ignore
        import io
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts: List[str] = []
        page_lengths: List[int] = []
        for i, page in enumerate(reader.pages, start=1):
            t = (page.extract_text() or "").strip()
            if t:
                parts.append(t)
                page_lengths.append(len(t))
                # Логируем первые 200 символов каждой страницы для отладки
                _dbg(f"pypdf PAGE {i}: len={len(t)}, preview={t[:200]}...")
        # Объединяем без маркеров страниц (для упрощения парсинга)
        text = "\n".join(parts).strip()
        if text:
            # Для отладки сохраняем с маркерами страниц
            debug_text = "\n\n".join([f"--- PAGE {i+1} ---\n{p}" for i, p in enumerate(parts)])
            PDF_TEXT_EXTRACT_PATH.write_text(debug_text, encoding="utf-8")
            _dbg(f"pypdf extracted pages={len(reader.pages)} text_len={len(text)}, page_lengths={page_lengths}")
        return text
    except Exception as e:
        _dbg(f"pypdf extract failed: {e}")
        return ""


# ==========================
# EXTRACT: Upload -> candidates/plain
# ==========================
def extract_text_from_upload(file_bytes: bytes, filename: str, mimetype: str) -> str:
    iam = get_iam_token()
    name = (filename or "").lower()

    # ---------- PDF ----------
    if mimetype == "application/pdf" or name.endswith(".pdf"):
        _dbg("PDF upload detected")

        direct_text = try_extract_text_from_pdf_bytes(file_bytes)
        direct_candidates = _smart_to_candidates(direct_text) if direct_text else ""
        _dbg(f"pypdf candidates_lines={len(direct_candidates.splitlines()) if direct_candidates else 0}")

        # Если pypdf дал уже достаточно строк — берём его (быстро)
        if direct_candidates and len(direct_candidates.splitlines()) >= 10:
            OCR_CANDIDATES_PATH.write_text(direct_candidates, encoding="utf-8")
            return direct_candidates.strip()

        # OCR async
        ocr_plain = ""
        ocr_candidates = ""
        try:
            op_id = ocr_pdf_async_start(iam, file_bytes)
            _dbg(f"OCR op_id={op_id}")

            # ждём done, но не бесконечно
            deadline = time.time() + OCR_PDF_OPERATION_WAIT_SEC
            sleep_s = 1.0
            done = False
            while time.time() < deadline:
                op = operations_get(iam, op_id)
                if op.get("done"):
                    done = True
                    if op.get("error"):
                        OCR_RAW_PATH.write_text(json.dumps(op, ensure_ascii=False, indent=2), encoding="utf-8")
                        raise RuntimeError(f"OCR PDF operation error: {op['error']}")
                    break
                time.sleep(sleep_s)
                sleep_s = min(3.0, sleep_s * 1.25)

            if not done:
                _dbg("OCR operation wait timeout (done=false). Using pypdf fallback if any.")
                if direct_candidates:
                    OCR_CANDIDATES_PATH.write_text(direct_candidates, encoding="utf-8")
                    return direct_candidates.strip()
                return direct_text.strip() if direct_text.strip() else ""

            recog_deadline = time.time() + OCR_GET_RECOGNITION_WAIT_SEC
            while time.time() < recog_deadline:
                res = ocr_pdf_get_recognition(iam, op_id)
                if res.get("_not_ready"):
                    time.sleep(2.0)
                    continue

                OCR_RAW_PATH.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
                ocr_plain = ocr_result_to_plaintext(res)
                OCR_PLAIN_PATH.write_text(ocr_plain or "", encoding="utf-8")

                ocr_candidates = _smart_to_candidates(ocr_plain or "")
                _dbg(f"OCR plain_len={len(ocr_plain)} candidates_lines={len(ocr_candidates.splitlines()) if ocr_candidates else 0}")
                break

        except Exception as e:
            _dbg(f"OCR failed: {e}")
            ocr_plain = ""
            ocr_candidates = ""

        merged_lines: List[str] = []
        for block in (direct_candidates, ocr_candidates):
            if block:
                merged_lines.extend([ln.strip() for ln in block.splitlines() if ln.strip()])
        merged = _dedup_lines_keep_order(merged_lines)

        OCR_CANDIDATES_PATH.write_text("\n".join(merged), encoding="utf-8")

        if merged:
            return "\n".join(merged).strip()
        if ocr_plain.strip():
            return ocr_plain.strip()
        if direct_text.strip():
            return direct_text.strip()
        return ""

    # ---------- Images ----------
    if mimetype in ("image/jpeg", "image/jpg") or name.endswith((".jpg", ".jpeg")):
        ocr = ocr_image_sync(iam, file_bytes, "image/jpeg")
    elif mimetype == "image/png" or name.endswith(".png"):
        ocr = ocr_image_sync(iam, file_bytes, "image/png")
    elif mimetype == "image/webp" or name.endswith(".webp"):
        ocr = ocr_image_sync(iam, file_bytes, "image/webp")
    else:
        raise RuntimeError(f"Неподдерживаемый тип: {mimetype} / {filename}")

    OCR_RAW_PATH.write_text(json.dumps(ocr, ensure_ascii=False, indent=2), encoding="utf-8")
    plain = ocr_result_to_plaintext(ocr)
    OCR_PLAIN_PATH.write_text(plain or "", encoding="utf-8")

    candidates = _smart_to_candidates(plain or "")
    OCR_CANDIDATES_PATH.write_text(candidates or "", encoding="utf-8")

    # если кандидаты пустые — вернём хотя бы plain, чтобы не было "пусто"
    return candidates.strip() if candidates.strip() else (plain or "").strip()


# ==========================
# PUBLIC: PDF отчёт
# ==========================
def generate_pdf_report(
    sex: str,
    age: int,
    raw_text: str = "",
    file_bytes: Optional[bytes] = None,
    filename: str = "",
    mimetype: str = "",
) -> tuple[Path, str]:
    raw_text = (raw_text or "").strip()

    # Создаём timestamp и uid в начале, чтобы использовать их и для исходного файла, и для отчёта
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_ts = created_at.replace(":", "-").replace(" ", "_")
    uid = uuid4().hex[:8]

    # Временно сохраняем исходный загруженный файл для тестирования
    original_file_path: Optional[Path] = None
    if file_bytes:
        # Определяем расширение файла
        if mimetype == "application/pdf" or (filename and filename.lower().endswith(".pdf")):
            original_file_path = OUT_DIR / f"original_{safe_ts}_{uid}.pdf"
        elif mimetype in ("image/jpeg", "image/jpg") or (filename and filename.lower().endswith((".jpg", ".jpeg"))):
            original_file_path = OUT_DIR / f"original_{safe_ts}_{uid}.jpg"
        elif mimetype == "image/png" or (filename and filename.lower().endswith(".png")):
            original_file_path = OUT_DIR / f"original_{safe_ts}_{uid}.png"
        elif mimetype == "image/webp" or (filename and filename.lower().endswith(".webp")):
            original_file_path = OUT_DIR / f"original_{safe_ts}_{uid}.webp"
        else:
            # Fallback: используем оригинальное имя или generic расширение
            ext = Path(filename).suffix if filename else ".bin"
            original_file_path = OUT_DIR / f"original_{safe_ts}_{uid}{ext}"
        
        original_file_path.write_bytes(file_bytes)
        _dbg(f"Сохранил исходный файл: {original_file_path.name} (размер: {len(file_bytes)} байт)")

    if not raw_text:
        if not file_bytes:
            raise ValueError("Нужно либо вставить текст анализов, либо загрузить файл (PDF/фото).")
        raw_text = (extract_text_from_upload(file_bytes, filename=filename, mimetype=mimetype) or "").strip()

    if not raw_text:
        raise ValueError("Не удалось получить текст из файла. См. outputs/ocr_debug.txt")

    # если это plain-текст — пытаемся собрать кандидатов
    if "\t" not in raw_text:
        candidates = _smart_to_candidates(raw_text)
        if candidates:
            raw_text = candidates

    # === BASELINE-FIRST + FALLBACK ===
    items = parse_with_fallback(raw_text)
    if not items:
        raise ValueError(
            "Не удалось собрать показатели.\n"
            "Проверьте:\n"
            "• outputs/ocr_plain.txt\n"
            "• outputs/ocr_candidates.txt\n"
            "• outputs/ocr_debug.txt\n"
        )

    _dbg(f"parse_with_fallback: итого {len(items)} items")
    for it in items[:5]:  # Логируем первые 5 для отладки
        _dbg(f"  item: {it.name} value={it.value} ref={format_range(it.ref)} status={it.status}")

    # === UNIVERSAL MODE: confidence + quality ===
    from parsers.quality import evaluate_parse_quality

    assign_confidence(items)
    items, dedup_dropped = deduplicate_items(items)
    _dbg(f"deduplicate_items: dropped {dedup_dropped} duplicates, {len(items)} items remain")

    # === SANITY FILTER (Этап 4.2) ===
    items, outlier_count = apply_sanity_filter(items)
    _dbg(f"apply_sanity_filter: отброшено {outlier_count} outliers, {len(items)} items remain")

    quality = evaluate_parse_quality(items, dedup_dropped_count=dedup_dropped, sanity_outlier_count=outlier_count)
    _dbg(f"quality: {quality}")

    low_quality = (
        quality["coverage_score"] < 0.6
        or quality["suspicious_count"] > 0
        or quality.get("ref_coverage_ratio", 1.0) < 0.5
        or quality.get("duplicate_name_count", 0) > 2
    )

    # Определяем тип панели анализов по наличию маркеров
    parsed_names_before = {it.name for it in items}
    panel_scores = detect_panel(parsed_names_before)
    _dbg(f"panel detection: {panel_scores}")
    
    # Порог для определения панели (минимальное количество маркеров)
    PANEL_THRESHOLD = 3
    
    # Проверка полноты парсинга (условно, только для обнаруженных панелей)
    missing_warnings: List[str] = []
    
    # Проверяем CBC только если обнаружена панель ОАК
    if panel_scores["cbc"] >= PANEL_THRESHOLD:
        cbc_expected_groups = {
            "основные_показатели": {"WBC", "RBC", "HGB", "HCT", "PLT"},
            "лейкоформула_проценты": {"NE%", "LY%", "MO%", "EO%", "BA%"},
        }
        
        for group_name, expected_names in cbc_expected_groups.items():
            missing = expected_names - parsed_names_before
            if missing:
                missing_str = ", ".join(sorted(missing))
                missing_warnings.append(f"Не найдены показатели группы '{group_name}': {missing_str}")
                _dbg(f"WARN: missing {group_name}: {missing}")
    
    # Если ни одна панель не обнаружена - показываем нейтральное предупреждение
    if max(panel_scores.values()) < PANEL_THRESHOLD and len(parsed_names_before) < 5:
        missing_warnings.append("Распознано мало показателей, возможно неполный разбор.")
        _dbg(f"WARN: low panel scores, total items: {len(parsed_names_before)}")

    # НЕ удаляем проценты - они важны для анализа лейкоформулы
    # Функция drop_percent_if_absolute теперь возвращает все items без изменений
    items = drop_percent_if_absolute(items)
    _dbg(f"after drop_percent_if_absolute: {len(items)} items (проценты сохранены)")

    # === БЕЗОПАСНЫЙ ОТБОР high_low: только confidence >= 0.7 ===
    high_low = [
        it for it in items
        if it.confidence >= 0.7
        and it.value is not None
        and it.ref is not None
        and it.status in ("ВЫШЕ", "НИЖЕ")
    ]
    _dbg(f"high_low deviations (confidence>=0.7): {len(high_low)} items")
    for it in high_low:
        _dbg(f"  deviation: {it.name} value={it.value} ref={format_range(it.ref)} "
             f"status={it.status} confidence={it.confidence}")

    # === ПОВЕДЕНИЕ ДЛЯ НЕИЗВЕСТНЫХ БЛАНКОВ ===
    # Если valid_value_count < 5 — не вызываем LLM
    if quality["valid_value_count"] < 5:
        _dbg(f"valid_value_count={quality['valid_value_count']} < 5 → пропускаем LLM")
        answer = (
            "Не удалось надёжно распознать достаточное количество показателей "
            "из документа. Попробуйте загрузить более чёткий файл/фото или "
            "другой формат. Таблица ниже может содержать частично распознанные данные."
        )
        high_low = []  # не показываем факты
    else:
        dict_expl = build_dict_explanations(high_low)
        specialists = suggest_specialists(high_low)
        llm_prompt = build_llm_prompt(sex, age, high_low, dict_expl, specialists)

        try:
            token = get_iam_token()
            answer = call_yandexgpt(token, llm_prompt)
            answer = re.sub(r"\n{3,}", "\n\n", answer).strip()
        except Exception as e:
            _dbg(f"LLM failed: {e}")
            answer = build_fallback_text(sex, age, items, high_low)

    # === UNIVERSAL DISCLAIMER при низком качестве ===
    if low_quality and quality["valid_value_count"] >= 5:
        disclaimer_prefix = (
            "⚠ Часть показателей не распознана надёжно из-за формата бланка/"
            "качества документа. Ниже приведены только уверенно распознанные "
            "результаты; некоторые отклонения могли не попасть в итог.\n\n"
        )
        answer = disclaimer_prefix + answer
        _dbg("universal disclaimer prepended to answer")

    context = build_template_context(sex, age, items, high_low, answer, missing_warnings)
    # Используем созданный ранее created_at для контекста (если нужно обновить, можно использовать context["created_at"])
    download_name = f"report_{safe_ts}_{uid}.pdf"

    html_path = OUT_DIR / f"report_{safe_ts}_{uid}.html"
    pdf_path = OUT_DIR / download_name

    rendered_html = render_html_report(context)
    html_path.write_text(rendered_html, encoding="utf-8")

    render_pdf_from_html(html_path, pdf_path, created_at)

    return pdf_path, download_name
