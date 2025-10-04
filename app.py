from flask import Flask, render_template, request, redirect, url_for, send_file, flash, send_from_directory
from datetime import datetime
import pandas as pd
from pathlib import Path
import os, re, json
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

# ---------------- Flags ----------------
COUNTRY_CODE = {
    "السعودية": "sa", "مصر": "eg", "باكستان": "pk", "الهند": "in", "بنغلاديش": "bd",
    "إندونيسيا": "id", "الفلبين": "ph", "نيجيريا": "ng", "اليمن": "ye", "الأردن": "jo",
    "سوريا": "sy", "فلسطين": "ps", "لبنان": "lb", "السودان": "sd", "المغرب": "ma",
    "الجزائر": "dz", "تونس": "tn", "تركيا": "tr",
}

def get_flag_url(nationality: str) -> str | None:
    if not nationality:
        return None
    nat = nationality.strip().replace("ـ", "").replace("  ", " ")
    cc = COUNTRY_CODE.get(nat)
    if not cc:
        for k, v in COUNTRY_CODE.items():
            if k in nat:
                cc = v
                break
    if not cc:
        return None
    return f"https://flagcdn.com/w80/{cc}.png"

# ---------------- Storage ----------------
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

# ---------------- Inference ----------------
MEDS_TO_CONDITIONS = {
    "باراسيتامول": ["ارتفاع حرارة", "ألم خفيف"],
    "إيبوبروفين": ["التهاب/ألم", "ارتفاع حرارة"],
    "أوميبرازول": ["ارتجاع/حموضة"],
    "محلول إماهة فموية ORS": ["جفاف", "إجهاد حراري"],
    "لوبراميد": ["إسهال"],
}

PHOTO_CONDITIONS = [
    "ارتفاع ضغط الدم",
    "سكري ||",
    "جلطة قلبيه",

]

def infer_conditions_from_meds(meds_text: str) -> list[str]:
    t = meds_text.lower()
    rules = [
        (r"ميتفورمين|metformin|انسولين|insulin", "سكري"),
        (r"أملوديبين|amlodipine|ضغط|hypertension", "ضغط مرتفع"),
        (r"سالبوتامول|بخاخ|salbutamol|ventolin|inhaler", "ربو محتمل"),
        (r"أوميبرازول|omeprazole|حموضة|ارتجاع|g r d|gerd", "ارتجاع/حموضة"),
        (r"وارفارين|warfarin|مميع|دواء سيولة", "سيولة/مضاد تخثر"),
        (r"ibuprofen|إيبوبروفين", "ألم/التهاب"),
        (r"paracetamol|باراسيتامول|panadol|بنادول", "ألم/حمّى"),
        (r"ors|محلول إماهة|rehydration", "جفاف/إجهاد حراري"),
        (r"لوبراميد|loperamide", "إسهال"),
    ]
    found = []
    for pat, label in rules:
        if re.search(pat, t):
            found.append(label)
    seen = set(); out = []
    for x in found:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

# ---------------- No cache (dev) ----------------
@app.after_request
def add_no_cache_headers(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ---------------- Excel schema ----------------
EXCEL_PATH = DATA_DIR / "submissions.xlsx"

COLUMNS = [
    "Timestamp",
    "Full Name",
    "Age",
    "Nationality",
    "Nusuk ID",
    "Phone",
    "Blood Type",
    "Chronic Conditions",      # ← سنملؤها من inferred_list عند الحاجة
    "Current Meds",
    "Inferred Conditions",
    "Meds Photo",
    "Record ID",
]

def append_to_excel(record: dict, excel_path: Path):
    """Upsert by Nusuk ID; coerce some columns to string to avoid dtype warnings."""
    df_new = pd.DataFrame([record], columns=COLUMNS)
    key_id = str(record.get("Nusuk ID", "")).strip()

    if excel_path.exists():
        df = pd.read_excel(excel_path)

        # تأكد من وجود كل الأعمدة
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""

        # أعمدة قد تكون رقمية → خلّيها نص عشان ما يصير FutureWarning
        for col in ["Age", "Phone", "Nusuk ID", "Record ID"]:
            if col in df.columns:
                df[col] = df[col].astype(str)

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

# ---------------- Routes ----------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    from datetime import datetime as dt
    import qrcode

    # --- Basic fields ---
    full_name   = request.form.get("full_name", "").strip()
    age         = request.form.get("age", "").strip()
    nationality = request.form.get("nationality", "").strip()
    nusuk_id    = request.form.get("nusuk_id", "").strip()
    phone       = request.form.get("phone", "").strip()
    blood_type  = request.form.get("blood_type", "").strip()

    if not full_name or not age or not nationality or not nusuk_id or not phone:
        flash("الرجاء تعبئة الاسم والعمر والجنسية ورقم نسك ورقم الجوال")
        return redirect(url_for("index"))

    # --- Meds (select / other) ---
    meds_selected = request.form.get("meds_select", "").strip()
    meds_other    = request.form.get("meds_other", "").strip()

    meds_text = meds_other if meds_selected == "أخرى" else (meds_selected or "")

    # --- Optional photo upload ---
    saved_file = None
    if "meds_image" in request.files:
        f = request.files.get("meds_image")
        if f and f.filename and allowed_file(f.filename):
            fname  = secure_filename(f.filename)
            unique = f"{dt.now().strftime('%Y%m%d%H%M%S')}_{fname}"
            f.save(UPLOAD_DIR / unique)
            saved_file = unique

    # --- Inference rules ---
    if saved_file:
        inferred_list = PHOTO_CONDITIONS
    elif meds_selected and meds_selected != "أخرى":
        inferred_list = MEDS_TO_CONDITIONS.get(meds_selected, [])
    else:
        inferred_list = []

    inferred_text = "، ".join(inferred_list) if inferred_list else ""

    # ✨ اجعل "الأمراض المزمنة" = inferred_list (عشان ما تطلع فاضية)
    chronic_text = inferred_text

    try:
        record = {
            "Timestamp": dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Full Name": full_name,
            "Age": str(age),
            "Nationality": nationality,
            "Nusuk ID": str(nusuk_id),
            "Phone": str(phone),
            "Blood Type": blood_type,

            "Chronic Conditions": chronic_text,   # ← تعبئة تلقائية
            "Current Meds": meds_text,
            "Inferred Conditions": inferred_text,
            "Meds Photo": saved_file,

            "Record ID": str(nusuk_id),
        }

        append_to_excel(record, EXCEL_PATH)

        # Save JSON snapshot
        rec_dir = DATA_DIR / "records"
        rec_dir.mkdir(exist_ok=True)
        rid = re.sub(r"[^0-9]+", "", nusuk_id) or nusuk_id
        with open(rec_dir / f"{rid}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # Create QR to person page
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

        qr_name = f"{dt.now().strftime('%Y%m%d%H%M%S')}_{re.sub(r'[^\w\-]+','_', full_name)[:32]}.png"
        img.save(qr_dir / qr_name)

        return render_template(
            "success.html",
            qr_url=url_for("qr_file", fname=qr_name),
            person_url=person_url,
            full_name=full_name,
            nusuk_id=nusuk_id,
            phone=phone
        )
    except Exception as e:
        flash(f"حدث خطأ أثناء الحفظ: {e}")
        return redirect(url_for("index"))

@app.route("/qr/<path:fname>")
def qr_file(fname):
    return send_file(DATA_DIR / "qr" / fname, mimetype="image/png")

@app.route("/p/<rid>")
def person_view(rid):
    rec_path = DATA_DIR / "records" / f"{rid}.json"
    if not rec_path.exists():
        flash("السجل غير موجود")
        return redirect(url_for("index"))

    with open(rec_path, "r", encoding="utf-8") as f:
        rec = json.load(f)

    flag_url = get_flag_url(rec.get("Nationality", ""))
    photo_name = (rec.get("Meds Photo") or "").strip()
    meds_photo_url = url_for("uploaded_file", fname=photo_name) if photo_name else None
    ts = int(datetime.now().timestamp())

    return render_template(
        "person.html",
        rec=rec,
        flag_url=flag_url,
        meds_photo_url=meds_photo_url,
        ts=ts,
    )

@app.route("/u/<path:fname>")
def uploaded_file(fname):
    return send_from_directory(UPLOAD_DIR, fname, as_attachment=False)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)