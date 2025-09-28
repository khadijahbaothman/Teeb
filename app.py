from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from datetime import datetime
import pandas as pd
from pathlib import Path
import os

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
    "National ID / Iqama",
    "Phone",
    "Emergency Phone",
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
    """Upsert a record into xlsx by Nusuk ID. If exists -> update row, else append."""
    df_new = pd.DataFrame([record], columns=COLUMNS)
    key_id = str(record.get("Nusuk ID", "")).strip()
    if excel_path.exists():
        df = pd.read_excel(excel_path)
        # Ensure all expected columns exist
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
        if key_id and "Nusuk ID" in df.columns and key_id in df["Nusuk ID"].astype(str).values:
            idx = df.index[df["Nusuk ID"].astype(str) == key_id][0]
            for col in COLUMNS:
                df.at[idx, col] = record.get(col, df.at[idx, col])
        else:
            df = pd.concat([df, df_new], ignore_index=True)
        df = df[COLUMNS]
        df.to_excel(excel_path, index=False, engine="openpyxl")
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

    national_id = request.form.get("national_id", "").strip()
    phone       = request.form.get("phone", "").strip()
    phone_emg   = request.form.get("phone_emg", "").strip()

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
        flash("الرجاء تعبئة الاسم والعمر والجنسية ورقم نسك ورقم الجوال")
        return redirect(url_for("index"))

    try:
        # 1) Prepare record
        record = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Full Name": full_name,
            "Age": age,
            "Nationality": nationality,
            "Nusuk ID": nusuk_id,
            "National ID / Iqama": national_id,
            "Phone": phone,
            "Emergency Phone": phone_emg,
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
        # 2) Upsert to Excel by Phone
        append_to_excel(record, EXCEL_PATH)

        # 3) Use Nusuk ID as record id
        rid = re.sub(r"[^0-9]+", "", nusuk_id) or nusuk_id
        record["Record ID"] = rid

        # 4) Save JSON snapshot
        REC_DIR = DATA_DIR / "records"
        REC_DIR.mkdir(exist_ok=True)
        with open(REC_DIR / f"{rid}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 5) Build public URL & QR
        base = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
        person_url = f"{base}/p/{rid}"

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

        qr_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{re.sub(r'[^\w\-]+','_', full_name)[:32]}.png"
        img.save(qr_dir / qr_name)

        print("QR URL =>", person_url)
        return render_template("success.html", qr_url=url_for("qr_file", fname=qr_name), person_url=person_url)
    except Exception as e:
        flash(f"حدث خطأ أثناء الحفظ: {e}")
        return redirect(url_for("index"))

    try:
        # Normalize date (keep as string in Excel but in ISO format)
        if visit_date:
            # trust input date as is; could convert to datetime if needed
            pass

        record = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Full Name": full_name,
            "Email": email,
            "Phone": phone,
            "Nationality": nationality,
            "City": city,
            "Visit Date": visit_date,
            "Purpose": purpose,
            "Notes": notes,
        }
        append_to_excel(record, EXCEL_PATH)
        return render_template("success.html", download_url=url_for("download_excel"))
    except Exception as e:
        flash(f"حدث خطأ أثناء الحفظ: {e}")
        return redirect(url_for("index"))


# Download route removed per request: no Excel download exposure.


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)

