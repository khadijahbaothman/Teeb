from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from datetime import datetime
import pandas as pd
from pathlib import Path
import os
from uuid import uuid4
import json
import os, re, qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

# Disable aggressive caching during development so CSS changes show immediately
@app.after_request
def add_no_cache_headers(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# Where we'll store the Excel workbook
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
EXCEL_PATH = DATA_DIR / "submissions.xlsx"

# Columns order for the Excel sheet
COLUMNS = [
    "Timestamp",
    "Full Name",
    "Age",
    "Nationality",
    "Nusuk ID",
    "Chronic Conditions",
    "Current Meds",
    "Allergies",
    "Vaccinations",
    "Temp (C)",
    "BP Systolic",
    "BP Diastolic",
    "Random Glucose (mg/dL)",
    "Medical Notes",
]


def append_to_excel(record: dict, excel_path: Path):
    """Append a single record (dict) to an xlsx file, creating it if missing."""
    df_new = pd.DataFrame([record], columns=COLUMNS)
    if excel_path.exists():
        # Load existing, append, and rewrite (simple & reliable)
        df_old = pd.read_excel(excel_path)
        df_all = pd.concat([df_old, df_new], ignore_index=True)
        # Keep only known columns (in case file was edited)
        for col in COLUMNS:
            if col not in df_all.columns:
                df_all[col] = ""
        df_all = df_all[COLUMNS]
        df_all.to_excel(excel_path, index=False, engine="openpyxl")
    else:
        df_new.to_excel(excel_path, index=False, engine="openpyxl")


@app.route("/", methods=["GET"]) 
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    from uuid import uuid4
    from datetime import datetime
    import json, os, re, qrcode

    # --- Basic fields ---
    full_name   = request.form.get("full_name", "").strip()
    age         = request.form.get("age", "").strip()
    nationality = request.form.get("nationality", "").strip()
    nusuk_id    = request.form.get("nusuk_id", "").strip()

    # --- Clinical text blocks ---
    chronic   = request.form.get("chronic", "").strip()
    meds      = request.form.get("meds", "").strip()
    allergies = request.form.get("allergies", "").strip()
    vacc      = request.form.get("vacc", "").strip()

    # --- Vitals ---
    temp_c   = request.form.get("temp_c", "").strip()
    bp_sys   = request.form.get("bp_sys", "").strip()
    bp_dia   = request.form.get("bp_dia", "").strip()
    rand_glu = request.form.get("rand_glu", "").strip()

    notes = request.form.get("notes", "").strip()

    # Required
    if not full_name or not age or not nationality or not nusuk_id:
        flash("الرجاء تعبئة الاسم والعمر والجنسية ورقم نسك")
        return redirect(url_for("index"))

    try:
        # 1) احفظ في Excel
        record = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Full Name": full_name,
            "Age": age,
            "Nationality": nationality,
            "Nusuk ID": nusuk_id,
            "Chronic Conditions": chronic,
            "Current Meds": meds,
            "Allergies": allergies,
            "Vaccinations": vacc,
            "Temp (C)": temp_c,
            "BP Systolic": bp_sys,
            "BP Diastolic": bp_dia,
            "Random Glucose (mg/dL)": rand_glu,
            "Medical Notes": notes,
        }
        append_to_excel(record, EXCEL_PATH)

        # 2) أنشئ معرّف وملف JSON
        rid = uuid4().hex[:10]
        record["Record ID"] = rid
        REC_DIR = DATA_DIR / "records"
        REC_DIR.mkdir(exist_ok=True)
        with open(REC_DIR / f"{rid}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 3) ابني الرابط العام (يستخدم BASE_URL إن وُجد)
        base = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
        person_url = f"{base}/p/{rid}"

        # 4) أنشئ QR واضح
        qr_dir = DATA_DIR / "qr"
        qr_dir.mkdir(parents=True, exist_ok=True)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4
        )
        qr.add_data(person_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        qr_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{re.sub(r'[^\\w\\-]+','_', full_name)[:32]}.png"
        img.save(qr_dir / qr_name)

        print("QR URL =>", person_url)  # يظهر في Logs على Render

        return render_template(
            "success.html",
            qr_url=url_for("qr_file", fname=qr_name),
            person_url=person_url
        )

    except Exception as e:
        flash(f"حدث خطأ أثناء الحفظ: {e}")
        return redirect(url_for("index"))


@app.route("/download")
def download_excel():
    if not EXCEL_PATH.exists():
        # If no file yet, create empty workbook with headers
        append_to_excel({c: "" for c in COLUMNS}, EXCEL_PATH)
        # and drop the empty row
        df = pd.read_excel(EXCEL_PATH)
        df = df.iloc[0:0]
        df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
    return send_file(EXCEL_PATH, as_attachment=True, download_name="submissions.xlsx")

@app.route("/qr/<path:fname>")
def qr_file(fname):
    return send_file(DATA_DIR / "qr" / fname, mimetype="image/png")

@app.route("/p/<rid>")
def person_view(rid):
    import json
    rec_path = DATA_DIR / "records" / f"{rid}.json"
    if not rec_path.exists():
        return "Record not found", 404
    with open(rec_path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    return render_template("person.html", rec=rec)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)

