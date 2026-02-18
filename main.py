import re
import subprocess
import sys
import html
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Set

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from playwright.sync_api import sync_playwright


# ==========================
# НАСТРОЙКИ YandexGPT
# ==========================
FOLDER_ID = "b1ghp3lahbvv6gmcofq9"
MODEL_URI = f"gpt://{FOLDER_ID}/yandexgpt/latest"
API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

TEMPERATURE = 0.2
MAX_TOKENS = 1300
TIMEOUT_SEC = 120

OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)
RAW_RESPONSE_PATH = OUT_DIR / "yc_raw_response.json"
HTML_REPORT_PATH = OUT_DIR / "report.html"
PDF_REPORT_PATH = OUT_DIR / "report.pdf"

TEMPLATES_DIR = Path("templates")
TEMPLATE_NAME = "report.html"  # templates/report.html

# "не намного" — порог в процентах за границей референса
WARN_PCT = 10.0  # можно менять на 5.0 / 15.0 и т.п.

SYSTEM_PROMPT = (
    "Ты — медицинский информационный помощник по лабораторным анализам.\n"
    "ЗАПРЕЩЕНО: ставить диагноз; назначать лечение; рекомендовать лекарства/дозировки; "
    "использовать запугивание.\n"
    "РАЗРЕШЕНО: объяснять показатели; отмечать отклонения; подсказать, что обсудить с врачом; "
    "каких специалистов имеет смысл обсудить/посетить; какие обследования можно обсудить.\n"
    "Стиль: спокойно, нейтрально. Формулировки: "
    "«может быть связано», «имеет смысл обсудить», «при необходимости».\n"
    "Опираться строго на ФАКТЫ ниже. Если данных мало — прямо скажи, что вывод ограничен."
)

# ==========================
# Справочник коротких объяснений (без ИИ)
# ==========================
EXPLAIN_DICT = {
    "ALT":  "ALT — фермент, часто используемый как индикатор состояния клеток печени и желчных путей.",
    "CHOL": "CHOL — общий холестерин: показатель липидного обмена; обычно оценивается вместе с LDL/HDL/ТГ и факторами риска.",
    "LDL":  "LDL — «условно нежелательная» фракция холестерина; оценивают в контексте общего сердечно-сосудистого риска.",
    "CREA": "CREA — креатинин: показатель для ориентировочной оценки функции почек (обычно вместе с расчётной СКФ).",
    "CRP":  "CRP — C-реактивный белок: маркёр воспаления (неспецифичный), интерпретируется вместе с симптомами и другими данными.",
    "GLUC": "GLUC — глюкоза: показатель углеводного обмена; интерпретация зависит от условий сдачи и повторных измерений.",
    "KF_ATR": "KF_ATR — лабораторное/нестандартизированное обозначение: важно уточнить расшифровку и методику у лаборатории или врача.",
}

# ==========================
# Карта "показатель -> специалисты" (НЕ диагноз, а логика направления обсуждения)
# ==========================
SPECIALIST_MAP = {
    "ALT": {"терапевт", "гастроэнтеролог"},
    "AST": {"терапевт", "гастроэнтеролог"},
    "TBIL": {"терапевт", "гастроэнтеролог"},
    "DBIL": {"терапевт", "гастроэнтеролог"},
    "ALB": {"терапевт"},
    "TP": {"терапевт"},
    "CHOL": {"терапевт", "кардиолог"},
    "LDL": {"терапевт", "кардиолог"},
    "HDL": {"терапевт", "кардиолог"},
    "TRIG": {"терапевт", "кардиолог"},
    "CREA": {"терапевт", "нефролог"},
    "UREA": {"терапевт", "нефролог"},
    "CRP": {"терапевт"},
    "GLUC": {"терапевт", "эндокринолог"},
    "KF_ATR": {"терапевт"},
}

# ==========================
# ВВОД
# ==========================
def read_sex_age() -> Tuple[str, int]:
    while True:
        sex = input("Пол (м/ж): ").strip().lower()
        if sex in ("м", "ж"):
            break
        print("Введите 'м' или 'ж'.")
    while True:
        s = input("Возраст (целое число): ").strip()
        if s.isdigit():
            age = int(s)
            break
        print("Введите возраст целым числом.")
    return sex, age


def read_multiline_input() -> str:
    print("Вставь текст анализов (можно табличкой). Пустая строка — закончить ввод.")
    lines = []
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.rstrip("\n")
        if line.strip() == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()

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


ALIASES = {
    "ALT": "ALT", "AST": "AST",
    "TBIL": "TBIL", "DBIL": "DBIL",
    "TP": "TP", "ALB": "ALB",
    "TRIG": "TRIG", "TG": "TRIG",
    "CHOL": "CHOL", "HDL": "HDL", "LDL": "LDL",
    "VLDLP": "VLDLP", "MG": "MG", "UREA": "UREA", "CREA": "CREA",
    "CRPN": "CRP", "CRP": "CRP",
    "GLUC": "GLUC", "GLU": "GLUC",
    "KF_ATR": "KF_ATR", "Kf Atr": "KF_ATR", "Kf Atr.": "KF_ATR",
    "NDBILL": "NDBILL",
}

def normalize_name(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw.strip())
    s_key = s.replace(" ", "_").replace("-", "_")
    if s in ALIASES:
        return ALIASES[s]
    if s_key in ALIASES:
        return ALIASES[s_key]
    if s_key.upper() in ALIASES:
        return ALIASES[s_key.upper()]
    return s_key.upper()

def parse_float(x: str) -> Optional[float]:
    x = x.strip().replace(",", ".")
    x = re.sub(r"[^\d\.\-]", "", x)
    try:
        return float(x)
    except Exception:
        return None

def parse_ref_range(text: str) -> Optional[Range]:
    t = text.strip()
    if not t:
        return None
    t = t.replace("—", "-").replace("–", "-").replace(",", ".")

    # Канонизация «до X» → «<X» (до удаления пробелов!)
    m_do = re.match(r"^[Дд]о\s*(\d+(?:\.\d+)?)$", t)
    if m_do:
        t = f"<{m_do.group(1)}"

    t = re.sub(r"\s+", "", t)

    m = re.match(r"^(<=|<|≤)(\d+(\.\d+)?)$", t)
    if m:
        return Range(low=None, high=float(m.group(2)))

    m = re.match(r"^(>=|>|≥)(\d+(\.\d+)?)$", t)
    if m:
        return Range(low=float(m.group(2)), high=None)

    m = re.match(r"^(-?\d+(\.\d+)?)-(-?\d+(\.\d+)?)$", t)
    if m:
        return Range(low=float(m.group(1)), high=float(m.group(3)))

    return None

def status_by_range(value: Optional[float], r: Optional[Range]) -> str:
    if value is None:
        return "НЕ РАСПОЗНАНО"
    if r is None:
        return "НЕИЗВЕСТНО"
    if r.low is not None and value < r.low:
        return "НИЖЕ"
    if r.high is not None and value > r.high:
        return "ВЫШЕ"
    return "В НОРМЕ"

def split_line(line: str) -> Tuple[str, str, str]:
    parts = [p for p in re.split(r"\t+", line.strip()) if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], "\t".join(parts[2:])
    parts = [p for p in re.split(r"\s+", line.strip()) if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    return line.strip(), "", ""

def extract_unit_and_ref(rest: str) -> Tuple[str, str]:
    r = rest.strip()
    if not r:
        return "", ""
    m = re.match(r"^(.+?)\s+([A-Za-zА-Яа-яµμ\/\^\d\*\.\-\×]+)$", r)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return r, ""

def format_range(r: Optional[Range]) -> str:
    if r is None:
        return "—"
    if r.low is None and r.high is not None:
        return f"< {r.high}"
    if r.low is not None and r.high is None:
        return f"> {r.low}"
    return f"{r.low}–{r.high}"

def parse_items(raw_text: str) -> List[Item]:
    items: List[Item] = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        raw_name, raw_val, rest = split_line(line)
        name = normalize_name(raw_name)
        ref_text, unit = extract_unit_and_ref(rest)
        value = parse_float(raw_val)
        ref = parse_ref_range(ref_text) if ref_text else None
        ref_source = "референс лаборатории" if ref else "нет"
        status = status_by_range(value, ref)
        items.append(Item(
            raw_name=raw_name.strip(),
            name=name,
            value=value,
            unit=unit,
            ref_text=ref_text,
            ref=ref,
            ref_source=ref_source,
            status=status,
        ))
    return items

def build_technical_report(items: List[Item]) -> str:
    lines = ["=== ТЕХНИЧЕСКИЙ РАЗБОР (ПО НОРМАМ) ===\n"]
    for it in items:
        v = "None" if it.value is None else f"{it.value:g}"
        unit = it.unit or ""
        lines.append(
            f"{it.name:<10} | {v:<10} {unit:<10} | норма: {format_range(it.ref):<12} | "
            f"источник: {it.ref_source:<20} | статус: {it.status}"
        )
    return "\n".join(lines)

def build_facts(items: List[Item]) -> Tuple[str, List[Item]]:
    high_low = [it for it in items if it.status in ("ВЫШЕ", "НИЖЕ")]
    lines = ["\n=== ФАКТЫ (ДЛЯ ПОЛЬЗОВАТЕЛЯ / НЕ ИИ) ===\n"]
    for it in high_low:
        lines.append(f"- {it.name} — {it.status.lower()} референса (источник нормы: {it.ref_source})")
    if not high_low:
        lines.append("Отклонений по распознанным нормам не найдено.")
    return "\n".join(lines), high_low

def build_dict_explanations(high_low: List[Item]) -> str:
    lines = ["\n=== ПОЯСНЕНИЯ (ИЗ СЛОВАРЯ, БЕЗ ИИ) ===\n"]
    if not high_low:
        lines.append("Нет отклонений — пояснения не требуются.")
        return "\n".join(lines)
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
# Раскраска статуса: зелёный/жёлтый/красный
# ==========================
def status_class_for_item(it: Item, warn_pct: float = WARN_PCT) -> str:
    if it.value is None or it.ref is None:
        return "muted"

    if it.status == "В НОРМЕ":
        return "status-normal"

    r = it.ref
    v = it.value

    if it.status == "ВЫШЕ":
        if r.high is not None:
            base = r.high
            if base == 0:
                return "status-high"
            pct = (v - base) / base * 100.0
            return "status-warn" if pct <= warn_pct else "status-high"
        return "status-high"

    if it.status == "НИЖЕ":
        if r.low is not None:
            base = r.low
            if base == 0:
                return "status-high"
            pct = (base - v) / base * 100.0
            return "status-warn" if pct <= warn_pct else "status-high"
        return "status-high"

    return "muted"

# ==========================
# YandexGPT
# ==========================
def get_iam_token() -> str:
    p = subprocess.run(["yc", "iam", "create-token"], capture_output=True, text=True, check=True)
    token = p.stdout.strip()
    if not token.startswith("t1."):
        raise RuntimeError("yc вернул не IAM-токен. Проверь yc config.")
    return token

def call_yandexgpt(iam_token: str, user_text: str) -> str:
    payload = {
        "modelUri": MODEL_URI,
        "completionOptions": {
            "stream": False,
            "temperature": TEMPERATURE,
            "maxTokens": str(MAX_TOKENS),
        },
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
    r = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT_SEC)
    RAW_RESPONSE_PATH.write_text(r.text, encoding="utf-8")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}. См. {RAW_RESPONSE_PATH}\n{r.text[:1200]}")
    data = r.json()
    return data["result"]["alternatives"][0]["message"]["text"]

def build_llm_prompt(sex: str, age: int, high_low: List[Item], dict_expl: str, specialist_list: List[str]) -> str:
    if not high_low:
        deviations = "Отклонений по распознанным нормам нет."
    else:
        deviations = "\n".join(
            [
                f"- {it.name}: {it.status} | значение {it.value:g} {it.unit or ''} | норма {format_range(it.ref)} | источник нормы: {it.ref_source}"
                for it in high_low
            ]
        )

    specialist_hint = ", ".join(specialist_list) if specialist_list else "—"

    prompt = f"""Пациент: пол {sex}, возраст {age}.

ФАКТЫ (это истина, не спорь с ними и не пересчитывай нормы):
{deviations}

Короткие справки (словарь, без ИИ):
{dict_expl}

Подсказка по специалистам (это НЕ направление и НЕ диагноз; это ориентир, кого можно обсудить):
{specialist_hint}

Сформируй итоговый ответ СТРОГО в таком виде (с заголовками как ниже).
Не добавляй показатели, которых нет в фактах. Не ставь диагноз. Не назначай лечение.
Не используй запугивание. В конце НЕ добавляй никаких маркеров типа "КОНЕЦ".

ДИСКЛЕЙМЕР  
(1–3 предложения)

КРАТКИЙ ИТОГ ПО ФАКТАМ  
(список только отклонений)

ЧТО ЭТО МОЖЕТ ОЗНАЧАТЬ  
(по каждому отклонению 1–2 строки, мягко; если KF_ATR — сказать «уточнить расшифровку/методику»)

ВАЖНО ПОНИМАТЬ  
(2–4 строки: отклонение не равно диагноз; важен контекст симптомов/анамнеза)

К КАКИМ СПЕЦИАЛИСТАМ ИМЕЕТ СМЫСЛ ОБРАТИТЬСЯ  
(список 2–5 специалистов; формулировка «планово/при необходимости»; опирайся на подсказку выше, но можешь сократить;
если данных мало — оставь «терапевт» + «по показаниям»)

ЧТО ИМЕЕТ СМЫСЛ ОБСУДИТЬ С ВРАЧОМ  
(6–8 пунктов, без лечения и лекарств)

ВОПРОСЫ ВРАЧУ  
(6–8 вопросов)

СРОЧНОСТЬ  
Два предложения максимум:
- «Планово обсудить с врачом.»
- «Если есть острые симптомы (боль в груди, выраженная слабость, желтушность, сильная одышка и т.п.) — обратиться за неотложной помощью.»
"""
    return prompt

# ==========================
# HTML (рендер Jinja2 шаблона)
# ==========================
def open_in_browser(path: Path):
    webbrowser.open(path.resolve().as_uri())

def build_template_context(sex: str, age: int, items: List[Item], high_low: List[Item], human_text: str) -> dict:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    facts: List[str] = []
    for it in high_low:
        code = html.escape(it.name)
        status = html.escape(it.status.lower())
        src = html.escape(it.ref_source)
        facts.append(f"<span class='mono'>{code}</span> — <strong>{status}</strong> референса (источник: {src})")

    rows = []
    for it in items:
        value_str = "" if it.value is None else f"{it.value:g}"
        rows.append({
            "code": it.name,
            "value": value_str,
            "unit": it.unit or "",
            "ref_text": it.ref_text or (format_range(it.ref) if it.ref else ""),
            "ref_source": it.ref_source,
            "status": it.status,
            "status_class": status_class_for_item(it, WARN_PCT),
        })

    explain_lines: List[str] = []
    for it in high_low:
        expl = EXPLAIN_DICT.get(it.name)
        if expl:
            explain_lines.append(f"<strong class='mono'>{html.escape(it.name)}</strong>: {html.escape(expl)}")

    context = {
        "sex": sex,
        "age": age,
        "created_at": created_at,
        "facts": facts,
        "rows": rows,
        "explain_lines": explain_lines,
        "human_text": human_text,
        "raw_path": str(RAW_RESPONSE_PATH),
    }
    return context

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
# PDF: HTML -> PDF + колонтитулы (дата/время + номера страниц)
# ==========================
def render_pdf_from_html(html_path: Path, pdf_path: Path, created_at: str) -> None:
    """
    Открывает локальный HTML как страницу Chromium и сохраняет PDF.
    Добавляет:
    - дату/время отчёта
    - номера страниц
    """
    if not html_path.exists():
        raise FileNotFoundError(f"HTML для PDF не найден: {html_path.resolve()}")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

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

        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")

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
# MAIN
# ==========================
def main():
    try:
        sex, age = read_sex_age()
        raw = read_multiline_input()
        if not raw:
            print("Пустой ввод. Нечего анализировать.")
            return

        items = parse_items(raw)

        tech = build_technical_report(items)
        facts_text, high_low = build_facts(items)
        dict_expl = build_dict_explanations(high_low)
        specialists = suggest_specialists(high_low)

        print("\n" + tech)
        print("\n" + facts_text)
        print("\n" + dict_expl)

        llm_prompt = build_llm_prompt(sex, age, high_low, dict_expl, specialists)

        print("\n\n=== РАСШИФРОВКА (ЧЕЛОВЕЧЕСКИ) ===\n")
        print("Обработка... (обычно 5–25 секунд)")

        token = get_iam_token()
        answer = call_yandexgpt(token, llm_prompt)
        answer = re.sub(r"\n{3,}", "\n\n", answer).strip()

        print(answer)
        print(f"\n(Сырой ответ API сохранён в: {RAW_RESPONSE_PATH})")

        context = build_template_context(
            sex=sex,
            age=age,
            items=items,
            high_low=high_low,
            human_text=answer,
        )

        # 1) HTML
        rendered_html = render_html_report(context)
        HTML_REPORT_PATH.write_text(rendered_html, encoding="utf-8")
        print(f"(HTML отчёт сохранён в: {HTML_REPORT_PATH})")

        # 2) PDF + колонтитулы
        render_pdf_from_html(HTML_REPORT_PATH, PDF_REPORT_PATH, context["created_at"])
        print(f"(PDF отчёт сохранён в: {PDF_REPORT_PATH})")

        # По желанию — открыть HTML
        open_in_browser(HTML_REPORT_PATH)
        # Если хочешь открывать PDF автоматически, раскомментируй:
        # open_in_browser(PDF_REPORT_PATH)

    except Exception as e:
        print("\nОШИБКА:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
