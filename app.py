from uuid import uuid4
from flask import Flask, request, render_template_string, send_file, redirect, url_for
from engine import generate_pdf_report

app = Flask(__name__)
app.secret_key = "dev"  # для MVP

# token -> (pdf_path, download_name)
REPORTS: dict[str, tuple[str, str]] = {}
MAX_REPORTS_IN_MEMORY = 50  # чтобы память не раздувалась на долгой работе сервера

FORM_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Расшифровка анализов → PDF</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:Arial, sans-serif; max-width:900px; margin:24px auto; padding:0 12px;}
    label{display:block; margin:12px 0 6px; font-weight:600;}
    input, select, textarea{width:100%; padding:10px; font-size:16px; box-sizing:border-box;}
    textarea{min-height:220px;}
    .row{display:grid; grid-template-columns:1fr 1fr; gap:12px;}
    .btn{margin-top:16px; padding:14px 16px; font-size:16px; cursor:pointer; width:100%;}
    .btn[disabled]{opacity:0.6; cursor:not-allowed;}
    .hint{color:#666; font-size:14px; margin-top:6px; line-height:1.35;}
    .err{background:#fff3f3; border:1px solid #ffb3b3; padding:10px; border-radius:8px; margin:12px 0;}
    .card{background:#f7f7f9; padding:14px; border-radius:10px; margin-bottom:16px;}

    .loader{
      display:none;
      margin-top:16px;
      text-align:center;
      padding:14px;
      border-radius:10px;
      background:#eef2ff;
      color:#1e3a8a;
      font-size:15px;
    }
    .spinner{
      width:28px;
      height:28px;
      border:4px solid #c7d2fe;
      border-top:4px solid #1e3a8a;
      border-radius:50%;
      animation: spin 1s linear infinite;
      margin:0 auto 10px;
    }
    @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .or{margin:12px 0; color:#666;}
  </style>
</head>
<body>

  <h2>Расшифровка анализов — PDF отчёт</h2>

  <div class="card">
    <div class="hint">
      Сервис носит справочный характер, не ставит диагноз и не назначает лечение.
      Отчёт предназначен для обсуждения с врачом.
    </div>
  </div>

  {% if error %}
    <div class="err"><strong>Ошибка:</strong> {{ error }}</div>
  {% endif %}

  <form method="post" action="/generate" enctype="multipart/form-data" onsubmit="startLoading()">
    <div class="row">
      <div>
        <label>Пол</label>
        <select name="sex" required>
          <option value="м" {% if sex=='м' %}selected{% endif %}>м</option>
          <option value="ж" {% if sex=='ж' %}selected{% endif %}>ж</option>
        </select>
      </div>
      <div>
        <label>Возраст</label>
        <input name="age" type="number" min="0" max="120" value="{{ age or 30 }}" required>
      </div>
    </div>

    <label>Загрузить PDF или фото анализов</label>
    <input type="file" name="file" accept=".pdf,image/*">
    <div class="hint">Поддержка: PDF, JPG/JPEG, PNG, WEBP.</div>

    <div class="or">— или —</div>

    <label>Текст анализов</label>
    <textarea name="raw_text" placeholder="Вставьте показатели построчно...">{{ raw_text or '' }}</textarea>
    <div class="hint">Обычно обработка занимает 10–30 секунд (PDF может чуть дольше).</div>

    <button id="submitBtn" class="btn" type="submit">Сформировать отчёт</button>

    <div id="loader" class="loader">
      <div class="spinner"></div>
      Идёт обработка и формирование PDF…<br>
      Пожалуйста, подождите.
    </div>
  </form>

  <script>
    function startLoading(){
      document.getElementById("submitBtn").disabled = true;
      document.getElementById("loader").style.display = "block";
    }
  </script>

</body>
</html>
"""

READY_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Отчёт готов</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:Arial, sans-serif; max-width:900px; margin:24px auto; padding:0 12px;}
    .card{background:#f7f7f9; padding:16px; border-radius:12px; margin-top:16px;}
    .btn{margin-top:14px; padding:14px 16px; font-size:16px; cursor:pointer; width:100%;}
    .hint{color:#666; font-size:14px; margin-top:8px; line-height:1.4;}
    .ok{font-size:18px; font-weight:700;}
  </style>
</head>
<body>
  <h2>Расшифровка анализов — PDF отчёт</h2>

  <div class="card">
    <div class="ok">✅ Отчёт готов</div>
    <div class="hint">
      Нажмите кнопку ниже, чтобы скачать PDF.
    </div>

    <form method="get" action="/download/{{ token }}">
      <button class="btn" type="submit">Скачать PDF</button>
    </form>

    <form method="get" action="/">
      <button class="btn" type="submit">Сформировать новый отчёт</button>
    </form>

    <div class="hint">
      Дисклеймер: отчёт носит справочный характер, не является диагнозом и назначением лечения.
    </div>
  </div>
</body>
</html>
"""


def _trim_reports_cache() -> None:
    # удаляем самые старые записи, если их слишком много
    if len(REPORTS) <= MAX_REPORTS_IN_MEMORY:
        return
    # dict сохраняет порядок вставки (Python 3.7+)
    to_drop = len(REPORTS) - MAX_REPORTS_IN_MEMORY
    for k in list(REPORTS.keys())[:to_drop]:
        REPORTS.pop(k, None)


@app.get("/")
def index():
    return render_template_string(FORM_HTML, error=None, sex="м", age=30, raw_text="")


@app.post("/generate")
def generate():
    try:
        sex = (request.form.get("sex", "м") or "м").strip().lower()
        if sex not in ("м", "ж"):
            raise ValueError("Пол должен быть 'м' или 'ж'.")

        age_raw = (request.form.get("age", "") or "").strip()
        raw_text = (request.form.get("raw_text", "") or "").strip()

        if not age_raw.isdigit():
            raise ValueError("Возраст должен быть целым числом.")
        age = int(age_raw)
        if age < 0 or age > 120:
            raise ValueError("Возраст должен быть в диапазоне 0–120.")

        # Файл (опционально)
        up = request.files.get("file")
        file_bytes = None
        filename = ""
        mimetype = ""
        if up and up.filename:
            file_bytes = up.read()
            if not file_bytes:
                raise ValueError("Файл пустой. Выберите другой файл.")
            filename = up.filename
            mimetype = up.mimetype or ""

        pdf_path, download_name = generate_pdf_report(
            sex=sex,
            age=age,
            raw_text=raw_text,
            file_bytes=file_bytes,
            filename=filename,
            mimetype=mimetype,
        )

        token = uuid4().hex
        REPORTS[token] = (str(pdf_path), download_name)
        _trim_reports_cache()

        return render_template_string(READY_HTML, token=token)

    except Exception as e:
        return render_template_string(
            FORM_HTML,
            error=str(e),
            sex=request.form.get("sex", "м"),
            age=request.form.get("age", ""),
            raw_text=request.form.get("raw_text", ""),
        )


@app.get("/download/<token>")
def download(token: str):
    if token not in REPORTS:
        return redirect(url_for("index"))

    pdf_path, download_name = REPORTS[token]
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
