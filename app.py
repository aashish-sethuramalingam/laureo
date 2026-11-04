"""Laureo: upload once, generate automatically, deliver accurately.

Run:  python -m streamlit run app.py
Owner: Person D (interface). The heavy lifting lives in modules/.
"""
import hmac
import html
import io
import os
import time
import zipfile

import streamlit as st
from PIL import Image

from modules import certificate as C
from modules import db
from modules import mailer as M
from modules import validator as V

st.set_page_config(page_title="Laureo", page_icon="🏅", layout="wide")
BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "generated_certificates")
OUTBOX = os.path.join(BASE, "outbox")
SAMPLE = os.path.join(BASE, "sample_data", "students.xlsx")
db.init()
ss = st.session_state

# ---------------------------------------------------------------- look & feel
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
.stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea, .stApp h1, .stApp h2, .stApp h3,
.stApp h4, .stApp button p, .stApp [data-testid="stMarkdownContainer"] {
    font-family: 'Plus Jakarta Sans', 'Source Sans Pro', sans-serif;
}
/* keep Streamlit's icon font intact (upload button, expander arrows) */
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {
    font-family: 'Material Symbols Rounded' !important;
}
[data-testid="stDecoration"], footer {visibility: hidden; height: 0;}
header[data-testid="stHeader"] {background: transparent;}
.block-container {padding-top: 3.2rem; max-width: 1180px;}

.cf-hero {background: linear-gradient(120deg, #1E3A8A 0%, #2747A8 60%, #3B5BC4 100%);
          border-radius: 18px; padding: 22px 28px; color: #fff; margin-bottom: 18px;
          box-shadow: 0 10px 30px rgba(30,58,138,.18);}
.cf-hero h1 {color: #fff !important; font-size: 1.9rem !important; font-weight: 800 !important;
             margin: 0 !important; padding: 0 !important; letter-spacing: -.02em;}
.cf-hero p {color: #DCE4FF !important; margin: 4px 0 14px 0 !important; font-size: .98rem;}
.cf-steps {display: flex; gap: 8px; flex-wrap: wrap;}
.cf-chip {padding: 6px 12px; border-radius: 999px; font-size: .82rem; font-weight: 600;
          background: rgba(255,255,255,.12); color: #C9D4FF; border: 1px solid rgba(255,255,255,.18);}
.cf-chip.done {background: rgba(201,162,39,.22); color: #FFE7A3; border-color: rgba(201,162,39,.5);}
.cf-chip.now {background: #fff; color: #1E3A8A; border-color: #fff;}

/* Theme-neutral colours: translucent fills + inherited text work in light AND dark mode */
.cf-card {border: 1px solid rgba(128,128,128,.28); border-radius: 14px; padding: 16px 18px;
          background: rgba(128,128,128,.05);}
.cf-stat {border-radius: 14px; padding: 14px 16px; border: 1px solid rgba(128,128,128,.25);
          background: rgba(99,123,230,.07);}
.cf-stat .n {font-size: 1.9rem; font-weight: 800; line-height: 1.1;}
.cf-stat .l {font-size: .72rem; opacity: .65; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.cf-stat.ok .n {color: #22A35A;} .cf-stat.warn .n {color: #E08A12;} .cf-stat.bad .n {color: #E04848;}
.cf-stat.blue .n {color: #4F78E8;}

.cf-mail {border: 1px solid rgba(128,128,128,.28); border-radius: 14px; overflow: hidden;}
.cf-mail .hd {background: rgba(128,128,128,.08); padding: 12px 16px; font-size: .86rem;
              border-bottom: 1px solid rgba(128,128,128,.22);}
.cf-mail .row {display: flex; gap: 10px; padding: 3px 0; align-items: flex-start;}
.cf-mail .row b {padding-top: 2px;}
.cf-mail .row b {opacity: .6; flex: 0 0 64px; font-weight: 600; font-size: .78rem; text-transform: uppercase;}
.cf-mail .row span {flex: 1; min-width: 0; word-break: break-word;}
.cf-mail .bd {padding: 14px 16px; white-space: pre-wrap; font-size: .9rem; line-height: 1.55;}
.cf-att {display: inline-block; margin-top: 4px; padding: 3px 10px; border-radius: 8px;
         background: rgba(79,120,232,.16); color: #5B82EC; font-size: .8rem; font-weight: 600; word-break: break-all;}
.cf-muted {opacity: .68; font-size: .88rem;}
</style>""", unsafe_allow_html=True)


def secret(key, default=""):
    """Read a setting from .streamlit/secrets.toml, then environment variables."""
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


def lan_base_url():
    """This computer's Wi-Fi address, e.g. http://192.168.1.5:8501, so phones can open QR links.

    'localhost' only works on the laptop itself; a phone scanning the QR needs the network address.
    """
    import socket
    port = st.get_option("server.port") or 8501
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))  # no data is sent; this just picks the active network card
            ip = sock.getsockname()[0]
        return f"http://{ip}:{port}"
    except OSError:
        return f"http://localhost:{port}"


# ---------------------------------------------------------------- session defaults
DEFAULTS = {
    "df": None, "recs": None, "batch_ids": [], "template_bytes": None, "smtp_session": {},
    "lay_name_y": 47.0, "lay_name_size": 7.5, "lay_body_y": 58.5, "lay_body_size": 3.0,
    "lay_footer_y": 90.5, "lay_color": "#1E3A8A", "lay_qr": True,
    "lay_qr_x": 85.0, "lay_qr_y": 78.0, "lay_qr_size": 15.0,
    "body_text": C.DEFAULT_BODY, "subject_tpl": M.DEFAULT_SUBJECT, "body_tpl": M.DEFAULT_BODY,
    "verify_base": secret("VERIFY_BASE_URL") or lan_base_url(),
    "tpl_src": "Built-in Laureo template", "autofix": False,
    "email_primary": None, "email_fallback": V.NONE, "delay": 1.0, "allow_resend": False,
    "test_email": "", "demo_mode": not secret("SMTP_PASSWORD"), "only_problems": True,
}
for ph in V.PLACEHOLDERS:
    DEFAULTS[f"map_{ph}"] = V.NONE
    DEFAULTS[f"def_{ph}"] = ""
for k, v in DEFAULTS.items():
    if k not in ss:
        ss[k] = v
    else:
        ss[k] = ss[k]  # keeps widget values alive when switching steps

STEPS = ["1 · Upload data", "2 · Map & validate", "3 · Design certificate",
         "4 · Preview & generate", "5 · Send & track"]
STATUS_LABEL = {"Pending": "⏳ Pending", "Generated": "📄 Generated", "Sending": "📤 Sending",
                "Sent": "✅ Sent", "Failed": "❌ Failed"}


# ---------------------------------------------------------------- helpers
def layout():
    return {
        "name_y": ss.lay_name_y / 100, "name_size": ss.lay_name_size / 100,
        "body_y": ss.lay_body_y / 100, "body_size": ss.lay_body_size / 100,
        "footer_y": ss.lay_footer_y / 100, "color": ss.lay_color, "qr": ss.lay_qr,
        "qr_x": ss.lay_qr_x / 100, "qr_y": ss.lay_qr_y / 100, "qr_size": ss.lay_qr_size / 100,
    }


@st.cache_resource
def builtin_template():
    return C.default_template()


def get_template():
    if ss.tpl_src.startswith("Upload") and ss.template_bytes:
        return Image.open(io.BytesIO(ss.template_bytes)).convert("RGB")
    return builtin_template()


def verify_url(cert_id):
    return f"{ss.verify_base.rstrip('/')}/?verify={cert_id}"


def smtp_cfg():
    cfg = {
        "host": secret("SMTP_HOST", "smtp.gmail.com"), "port": secret("SMTP_PORT", "587"),
        "user": secret("SMTP_USER"), "password": secret("SMTP_PASSWORD"),
        "sender_name": secret("SENDER_NAME", "Event Team"),
    }
    cfg.update({k: v for k, v in ss.smtp_session.items() if v})
    cfg["sender_email"] = secret("SENDER_EMAIL") or cfg["user"]
    return cfg


def enrich(rec):
    rec = dict(rec)
    rec["VERIFY_URL"] = verify_url(rec["CERT_ID"])
    rec["SENDER_NAME"] = smtp_cfg()["sender_name"]
    return rec


def db_row_to_rec(r):
    return enrich({"NAME": r["name"], "ID": r["student_id"], "EMAIL": r["email"], "EVENT": r["event"],
                   "ACHIEVEMENT": r["achievement"], "DATE": r["date"], "CERT_TYPE": r["cert_type"],
                   "CERT_ID": r["cert_id"]})


def load_df(df, source):
    """New spreadsheet: reset everything downstream and pre-fill smart mapping."""
    ss.df, ss.recs, ss.batch_ids, ss.source = df, None, [], source
    ecols = V.email_columns(df)
    sug = V.suggest_mapping([c for c in df.columns if c not in ecols])
    for ph in V.PLACEHOLDERS:
        ss[f"map_{ph}"] = sug[ph]
    ss.email_primary = ecols[0] if ecols else df.columns[0]
    ss.email_fallback = ecols[1] if len(ecols) > 1 else V.NONE


def go_to(i):
    ss.step = STEPS[i]


def next_button(i, label, disabled=False):
    st.button(label, type="primary", on_click=go_to, args=(i,), disabled=disabled, key=f"next_{i}")


def stat(col, label, value, tone="blue"):
    col.markdown(f'<div class="cf-stat {tone}"><div class="l">{label}</div><div class="n">{value}</div></div>',
                 unsafe_allow_html=True)


def mail_card(rec, subject, body, attachment):
    st.markdown(
        f'<div class="cf-mail"><div class="hd">'
        f'<div class="row"><b>From</b><span>{html.escape(smtp_cfg()["sender_name"])}</span></div>'
        f'<div class="row"><b>To</b><span>{html.escape(rec["EMAIL"])}</span></div>'
        f'<div class="row"><b>Subject</b><span><strong>{html.escape(C.fill(subject, rec))}</strong></span></div>'
        f'<div class="row"><b>File</b><span><span class="cf-att">📎 {html.escape(attachment)}</span></span></div>'
        f'</div>'
        f'<div class="bd">{html.escape(C.fill(body, rec))}</div></div>',
        unsafe_allow_html=True)


# ---------------------------------------------------------------- public verification page (QR target)
verify_id = st.query_params.get("verify")
if verify_id:
    r = db.get(verify_id)
    st.markdown('<div class="cf-hero"><h1>🔎 Certificate verification</h1>'
                '<p>Checked against Laureo\'s official records</p></div>', unsafe_allow_html=True)
    if r:
        st.success(f"✅ Valid certificate · {verify_id}")
        st.markdown(f'<div class="cf-card"><div class="cf-muted">Awarded to</div>'
                    f'<h2 style="margin:0 0 10px 0">{html.escape(r["name"])}</h2>'
                    f'<b>Event:</b> {html.escape(r["event"])}<br><b>Achievement:</b> {html.escape(r["achievement"])}'
                    f'<br><b>Date:</b> {html.escape(r["date"])}</div>', unsafe_allow_html=True)
        delivered = (f"Delivered by email on {r['sent_at']}" if r.get("sent_at")
                     else "Issued, email delivery pending")
        st.caption(f"Issued {r['created_at']} · {delivered}")
    else:
        st.error("❌ No certificate with this ID exists. It may be fake or mistyped.")
    st.stop()

# ---------------------------------------------------------------- organiser login (Rule 15)
app_password = secret("APP_PASSWORD")
if app_password and not ss.get("authed"):
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div class="cf-hero"><h1>🏅 Laureo</h1><p>Organiser login</p></div>',
                    unsafe_allow_html=True)
        pw = st.text_input("Password", type="password")
        if st.button("Log in", type="primary", width="stretch"):
            if hmac.compare_digest(pw, app_password):
                ss.authed = True
                st.rerun()
            st.error("Wrong password")
    st.stop()

# ---------------------------------------------------------------- sidebar + header
with st.sidebar:
    st.markdown("### 🏅 Laureo")
    st.caption("Upload once. Generate automatically. Deliver accurately.")
    step = st.radio("Workflow", STEPS, key="step", label_visibility="collapsed")
    st.divider()
    status_box = st.empty()  # filled at the end of the run, so it is never one step behind
    st.caption("🌓 Light / dark: ⋮ menu (top right) → Settings → Theme. Follows your computer by default.")


def render_status():
    done = [ss.df is not None, ss.recs is not None, bool(ss.batch_ids)]
    sent = 0
    if ss.batch_ids:
        recs = db.records(ss.batch_ids)
        sent = int((recs.status == "Sent").sum()) if len(recs) else 0
    lines = [("Data uploaded", done[0]), ("Validated", done[1]), ("Certificates generated", done[2]),
             (f"Delivered {sent}/{len(ss.batch_ids)}" if ss.batch_ids else "Delivered", sent > 0)]
    text = "<br>".join(("✅ " if ok else "<span style='opacity:.45'>○</span> ") + label for label, ok in lines)
    if not app_password:
        text += "<br><span style='opacity:.6'>🔓 No organiser password set</span>"
    status_box.markdown(f"<div style='line-height:1.9;font-size:.92rem'><b>Progress</b><br>{text}</div>",
                        unsafe_allow_html=True)


current = STEPS.index(step)
if ss.get("last_step") != step:  # jump back to the top when the step changes
    ss.last_step = step
    try:
        import streamlit.components.v1 as components
        components.html(
            "<script>const top = () => { const d = window.parent.document;"
            "['[data-testid=\"stMain\"]', 'section.main', '[data-testid=\"stAppViewContainer\"]']"
            ".forEach(q => { const e = d.querySelector(q); if (e) e.scrollTo(0, 0); });"
            "window.parent.scrollTo(0, 0); };"
            "[0, 120, 350, 700].forEach(t => setTimeout(top, t));</script>", height=0)
    except Exception:
        pass
done_flags = [ss.df is not None, ss.recs is not None, ss.recs is not None, bool(ss.batch_ids), False]
chips = "".join(
    f'<span class="cf-chip {"now" if i == current else ("done" if done_flags[i] else "")}">'
    f'{"✓ " if done_flags[i] and i != current else ""}{s}</span>'
    for i, s in enumerate(STEPS))
st.markdown(f'<div class="cf-hero"><h1>🏅 Laureo</h1>'
            f'<p>Upload once. Generate automatically. Deliver accurately.</p>'
            f'<div class="cf-steps">{chips}</div></div>', unsafe_allow_html=True)


def need(cond, message, back=None):
    if not cond:
        st.info(message)
        if back is not None:
            st.button(f"Go to {STEPS[back]}", on_click=go_to, args=(back,))
        render_status()
        st.stop()


# ================================================================ STEP 1
if current == 0:
    left, right = st.columns([1.6, 1])
    with left:
        up = st.file_uploader("Student spreadsheet (Excel or CSV)", type=["xlsx", "csv"])
        if up is not None and ss.get("source") != f"{up.name}:{up.size}":
            try:
                load_df(V.load_table(up), f"{up.name}:{up.size}")
            except Exception as e:
                st.error(f"Could not read this file: {e}")
        if st.button("✨ Use sample data", help="52 students with deliberate mistakes, to see validation in action"):
            load_df(V.load_table(SAMPLE), "sample")
    with right:
        st.markdown('<div class="cf-card"><b>What your file needs</b><br>'
                    '<span class="cf-muted">One row per student. Column names can be anything; '
                    'we detect them.</span><br><br>'
                    '✔ Student name<br>✔ Email (a second email column works as fallback)<br>'
                    '➕ Optional: ID, event, achievement, date, certificate type<br><br>'
                    '<span class="cf-muted">Title rows, extra sheets and blank rows are skipped '
                    'automatically.</span></div>', unsafe_allow_html=True)

    if ss.df is not None:
        st.write("")
        c1, c2, c3 = st.columns(3)
        stat(c1, "Students found", len(ss.df))
        stat(c2, "Columns", len(ss.df.columns))
        sheet = ss.df.attrs.get("sheet")
        stat(c3, "Headers on row", ss.df.attrs.get("header_row", 1))
        if sheet not in (None, "csv"):
            st.caption(f"Reading sheet **{sheet}**")
        st.dataframe(ss.df, hide_index=True, height=300)
        next_button(1, "Next: map & validate →")

# ================================================================ STEP 2
elif current == 1:
    need(ss.df is not None, "Upload a file first.", back=0)
    df = ss.df
    cols = list(df.columns)
    mapping = {ph: ss[f"map_{ph}"] for ph in V.PLACEHOLDERS}
    defaults = {ph: ss[f"def_{ph}"] for ph in V.PLACEHOLDERS}
    if mapping["NAME"] == V.NONE or mapping["NAME"] not in cols:
        st.error("Choose which column holds the student name in section ② below.")
        recs = None
    else:
        recs = V.build_records(df, mapping, defaults, ss.email_primary, ss.email_fallback, ss.autofix)
        ss.recs = recs

    # ---------- summary
    if recs is not None:
        counts = recs.STATUS.value_counts()
        ready = int(counts.get("OK", 0) + counts.get("Warning", 0))
        blocked = int(counts.get("Error", 0))
        c1, c2, c3, c4 = st.columns(4)
        stat(c1, "Total rows", len(recs))
        stat(c2, "Ready to go", ready, "ok")
        stat(c3, "Auto-fixed / notes", int(counts.get("Warning", 0)), "warn")
        stat(c4, "Need fixing", blocked, "bad")
        st.write("")

    # ---------- ① fix problems
    with st.container(border=True):
        st.markdown("#### ① Fix problem rows")
        if recs is None:
            st.caption("Set the name column first.")
        elif blocked == 0:
            st.success("Nothing to fix. Every row is ready.")
        else:
            st.markdown('<span class="cf-muted">Click any cell below and type the correct value, '
                        'or tick <b>Remove</b> to leave that student out. Then press <b>Save fixes</b>. '
                        'Your original Excel file is never changed.</span>', unsafe_allow_html=True)
            typos = recs[recs.ISSUES.str.contains("Likely email typo", na=False)]
            if len(typos) and not ss.autofix:
                st.button(f"✨ Auto-fix {len(typos)} email typo(s) for me",
                          on_click=lambda: ss.update(autofix=True))

            problem = recs[recs.STATUS == "Error"]
            edit_cols = [c for c in [mapping["NAME"], ss.email_primary, ss.email_fallback]
                         if c and c != V.NONE and c in cols]
            edit_cols = list(dict.fromkeys(edit_cols))  # no duplicates, keep order
            table = df.loc[problem.ROW.astype(int), edit_cols].copy()
            table.insert(0, "Row", table.index.astype(int))
            table["Remove"] = False
            table["Problem"] = problem.ISSUES.str.split(";").str[0].values

            with st.form(f"fix_form_{ss.get('fix_version', 0)}"):
                edited = st.data_editor(
                    table, hide_index=True, width="stretch",
                    disabled=["Row", "Problem"],
                    column_config={
                        "Row": st.column_config.NumberColumn("Excel row", width="small"),
                        "Problem": st.column_config.TextColumn("⚠️ Problem", width="medium"),
                        "Remove": st.column_config.CheckboxColumn("Remove", width="small",
                                                                  help="Leave this student out"),
                        **{c: st.column_config.TextColumn(f"✏️ {c}", width="medium") for c in edit_cols},
                    })
                if st.form_submit_button("💾 Save fixes", type="primary"):
                    new_df = df.copy()
                    drop = []
                    for _, r in edited.iterrows():
                        row = int(r["Row"])
                        if r["Remove"]:
                            drop.append(row)
                            continue
                        for c in edit_cols:
                            new_df.at[row, c] = str(r[c] or "").strip()
                    new_df = new_df.drop(index=drop)
                    new_df.attrs = df.attrs
                    ss.df = new_df
                    ss.fix_version = ss.get("fix_version", 0) + 1
                    ss.fix_note = f"Saved. {len(drop)} removed." if drop else "Saved. Rows re-checked."
                    st.rerun()
            if ss.get("fix_note"):
                st.caption("✅ " + ss.pop("fix_note"))

        if recs is not None:
            notes = recs[recs.STATUS == "Warning"]
            if len(notes):
                with st.expander(f"ℹ️ {len(notes)} row(s) we adjusted automatically (no action needed)"):
                    st.dataframe(notes[["ROW", "NAME", "ISSUES"]], hide_index=True, width="stretch",
                                 column_config={"ROW": "Excel row", "NAME": "Name", "ISSUES": "What we did"})

    # ---------- ② column matching
    with st.container(border=True):
        st.markdown("#### ② Check column matching")
        st.markdown('<span class="cf-muted">We matched your columns automatically. Check the '
                    '<b>Example</b> looks right. If not, pick another column. Use <b>If blank</b> to give '
                    'everyone the same value, e.g. the event name.</span>', unsafe_allow_html=True)
        first = df.iloc[0] if len(df) else None
        clean_first = recs.iloc[0] if recs is not None and len(recs) else None
        h1, h2, h3, h4 = st.columns([1.1, 1.3, 1.3, 1.2])
        for h, t in zip((h1, h2, h3, h4), ("Certificate field", "Your column", "Example", "If blank, use")):
            h.markdown(f"<span class='cf-muted'><b>{t}</b></span>", unsafe_allow_html=True)
        info = {"NAME": "Student name ✱", "ID": "Student ID", "EVENT": "Event", "ACHIEVEMENT": "Achievement",
                "DATE": "Date", "CERT_TYPE": "Certificate type"}
        for ph in V.PLACEHOLDERS:
            a, b, c, d = st.columns([1.1, 1.3, 1.3, 1.2], vertical_alignment="center")
            a.markdown(f"**{info[ph]}**  \n<span class='cf-muted'>{{{{{ph}}}}}</span>", unsafe_allow_html=True)
            b.selectbox(info[ph], [V.NONE] + cols, key=f"map_{ph}", label_visibility="collapsed")
            col = ss[f"map_{ph}"]
            example = ""
            if clean_first is not None and col in cols:
                example = clean_first[ph]
            example = example or ss[f"def_{ph}"]
            c.markdown(f"`{example}`" if example else "<span class='cf-muted'>(empty)</span>",
                       unsafe_allow_html=True)
            d.text_input(f"Default {ph}", key=f"def_{ph}", label_visibility="collapsed",
                         placeholder="IEEE Hackathon 2026" if ph == "EVENT" else "optional")
        st.caption("✱ required")

    # ---------- ③ email
    with st.container(border=True):
        st.markdown("#### ③ Which email to send to")
        a, b = st.columns(2)
        a.selectbox("Send to this column", cols, key="email_primary")
        b.selectbox("If that one is empty or wrong, use", [V.NONE] + cols, key="email_fallback")
        if first is not None:
            st.caption(f"Example: {first.get(ss.email_primary, '')}"
                       + (f"  ·  fallback {first.get(ss.email_fallback, '')}" if ss.email_fallback in cols else ""))
        st.checkbox("Auto-fix obvious email typos (gmial.com → gmail.com)", key="autofix")

    if recs is not None:
        a, b = st.columns([1, 1])
        a.download_button("⬇ Download problem report (CSV)", recs[recs.STATUS != "OK"].to_csv(index=False),
                          "laureo_problems.csv", "text/csv")
        msg = (f"Next: design certificate for {ready} students →" if blocked == 0 else
               f"Continue with {ready} ready students ({blocked} skipped) →")
        next_button(2, msg, disabled=ready == 0)

# ================================================================ STEP 3
elif current == 2:
    need(ss.recs is not None, "Validate your data first.", back=1)
    sample = ss.recs[ss.recs.STATUS != "Error"]
    need(len(sample), "No valid rows to preview. Fix the errors first.", back=1)
    preview, controls = st.columns([1.55, 1])
    with controls:
        if ss.tpl_src not in ("Built-in Laureo template", "Upload my own (PNG/JPG)"):
            ss.tpl_src = "Built-in Laureo template"
        st.radio("Template", ["Built-in Laureo template", "Upload my own (PNG/JPG)"], key="tpl_src",
                 horizontal=True)
        if ss.tpl_src.startswith("Upload"):
            f = st.file_uploader("Template image (A4 landscape works best)", type=["png", "jpg", "jpeg"])
            if f is not None:
                ss.template_bytes = f.getvalue()
            if not ss.template_bytes:
                st.caption("Showing the built-in template until you upload one.")
        t_text, t_pos, t_qr = st.tabs(["✏️ Text", "📐 Layout", "🔳 QR code"])
        with t_text:
            st.text_area("Line under the name (use {{PLACEHOLDERS}})", key="body_text", height=90)
            st.caption("Available: {{NAME}} {{ID}} {{EVENT}} {{ACHIEVEMENT}} {{DATE}} {{CERT_TYPE}}")
            st.color_picker("Name colour", key="lay_color")
        with t_pos:
            st.slider("Name: height on page (%)", 10.0, 90.0, step=0.5, key="lay_name_y")
            st.slider("Name: size", 2.0, 15.0, step=0.5, key="lay_name_size")
            st.slider("Text: height on page (%)", 10.0, 95.0, step=0.5, key="lay_body_y")
            st.slider("Text: size", 1.0, 6.0, step=0.1, key="lay_body_size")
            st.slider("Certificate ID line (%)", 50.0, 98.0, step=0.5, key="lay_footer_y")
        with t_qr:
            st.checkbox("Add QR verification code", key="lay_qr")
            st.slider("Left / right (%)", 5.0, 95.0, step=0.5, key="lay_qr_x")
            st.slider("Up / down (%)", 5.0, 95.0, step=0.5, key="lay_qr_y")
            st.slider("Size", 5.0, 30.0, step=0.5, key="lay_qr_size")
            st.text_input("Verification link (your app's address)", key="verify_base",
                          help="Detected automatically from your Wi-Fi. Phones scanning the QR open this address.")
            st.button("↻ Re-detect my Wi-Fi address", on_click=lambda: ss.update(verify_base=lan_base_url()))
            st.caption("Phones must be on the **same Wi-Fi** as this laptop. If you change networks, "
                       "re-detect and generate the certificates again.")
    with preview:
        rec = enrich(sample.iloc[0].to_dict())
        st.image(C.render(get_template(), rec, layout(), ss.body_text, rec["VERIFY_URL"]))
        st.caption(f"Live preview using {rec['NAME']}. Long names shrink automatically to fit.")
        next_button(3, "Next: preview & generate →")

# ================================================================ STEP 4
elif current == 3:
    need(ss.recs is not None, "Validate your data first.", back=1)
    valid = ss.recs[ss.recs.STATUS != "Error"].reset_index(drop=True)
    need(len(valid), "No valid rows. Fix the errors first.", back=1)

    with st.container(border=True):
        a, b = st.columns([2, 1], vertical_alignment="center")
        a.markdown(f"**{len(valid)} certificates ready to generate**  \n"
                   f'<span class="cf-muted">Each gets a unique ID, a QR code and a systematic file name.</span>',
                   unsafe_allow_html=True)
        generate = b.button("⚙️ Generate all", type="primary", width="stretch")
        if generate:
            os.makedirs(OUT_DIR, exist_ok=True)
            tpl, lay = get_template(), layout()
            bar = st.progress(0.0, text="Starting...")
            made = skipped = 0
            for i, row in valid.iterrows():
                r = enrich(row.to_dict())
                path = os.path.join(OUT_DIR, C.file_name(r))
                if db.upsert(r, path, "Pending") == "Sent":
                    skipped += 1  # already delivered earlier; never regenerate or resend by accident
                else:
                    C.save_pdf(C.render(tpl, r, lay, ss.body_text, r["VERIFY_URL"]), path, r)
                    db.set_status(r["CERT_ID"], "Generated")
                    made += 1
                bar.progress((i + 1) / len(valid), text=f"{i + 1}/{len(valid)} · {r['NAME']}")
            ss.batch_ids = list(valid.CERT_ID)
            st.success(f"Generated {made} certificates." + (f" Skipped {skipped} already sent." if skipped else ""))
        if ss.batch_ids:
            rows = db.records(ss.batch_ids)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in rows.file_path:
                    if os.path.exists(p):
                        z.write(p, os.path.basename(p))
            c1, c2 = st.columns(2)
            c1.download_button("⬇ Download all certificates (ZIP)", buf.getvalue(), "certificates.zip",
                               "application/zip", width="stretch")
            st.link_button(f"📱 Test a QR verification link ({ss.verify_base})",
                           verify_url(ss.batch_ids[0]), width="stretch")
            with c2:
                st.button("Next: send & track →", type="primary", on_click=go_to, args=(4,),
                          width="stretch", key="next_4")

    st.markdown("#### Preview any student")
    pick = st.selectbox("Student", valid.index, label_visibility="collapsed",
                        format_func=lambda i: f"{valid.at[i, 'NAME']}  ·  {valid.at[i, 'EMAIL']}")
    rec = enrich(valid.loc[pick].to_dict())
    fname = C.file_name(rec)
    left, right = st.columns([1.35, 1])
    with left:
        st.image(C.render(get_template(), rec, layout(), ss.body_text, rec["VERIFY_URL"]))
        st.success(f"🔒 Match check: this attachment carries certificate ID **{rec['CERT_ID']}**, "
                   f"which belongs only to {rec['NAME']}.")
    with right:
        mail_card(rec, ss.subject_tpl, ss.body_tpl, fname)
        with st.expander("✏️ Edit email template"):
            st.text_input("Subject", key="subject_tpl")
            st.text_area("Body", key="body_tpl", height=230)
            st.caption("Placeholders: {{NAME}} {{EVENT}} {{ACHIEVEMENT}} {{DATE}} {{CERT_ID}} {{VERIFY_URL}}")

# ================================================================ STEP 5
elif current == 4:
    need(ss.batch_ids, "Generate certificates first.", back=3)
    cfg = smtp_cfg()

    def send_batch(cert_ids, test_to=None):
        cfg = smtp_cfg()
        if ss.demo_mode:
            cfg["sender_email"] = cfg["sender_email"] or "certificates@laureo.demo"
        elif not (cfg["user"] and cfg["password"]):
            st.error("Set up the email account first, or turn on Demo mode.")
            return
        rows = db.records(cert_ids)
        if not test_to and not ss.allow_resend:
            rows = rows[rows.status != "Sent"]
        if rows.empty:
            st.info("Nothing to send. Everyone in this batch already has their certificate.")
            return
        bar = st.progress(0.0, text="Preparing outbox..." if ss.demo_mode else "Connecting to mail server...")
        try:
            server = (M.DemoMailer(OUTBOX) if ss.demo_mode
                      else M.Mailer(cfg["host"], cfg["port"], cfg["user"], cfg["password"]))
            delivered = 0
            with server as mail:
                for n, (_, r) in enumerate(rows.iterrows(), start=1):
                    rec = db_row_to_rec(r)
                    # Rule 6 safety gate: file must exist and carry this student's certificate ID
                    if not (os.path.exists(r.file_path) and r.cert_id in os.path.basename(r.file_path)
                            and V.EMAIL_RE.match(r.email)):
                        db.set_status(r.cert_id, "Failed", "Safety check failed: attachment and recipient do not match")
                        continue
                    if not test_to:
                        db.set_status(r.cert_id, "Sending")
                    try:
                        msg = M.build_message(
                            rec, ("[TEST] " if test_to else "") + ss.subject_tpl, ss.body_tpl,
                            cfg["sender_email"], cfg["sender_name"], r.file_path, to_override=test_to)
                        mail.send(msg)
                        delivered += 1
                        if not test_to:
                            db.set_status(r.cert_id, "Sent")
                    except Exception as e:  # Rule 12: one failure never stops the batch
                        db.set_status(r.cert_id, "Failed", str(e)[:200])
                    bar.progress(n / len(rows), text=f"{n}/{len(rows)} · {rec['NAME']}")
                    if not ss.demo_mode:
                        time.sleep(ss.delay)
        except Exception as e:
            st.error(f"Could not connect or log in to the mail server: {e}")
            if "gmail" in cfg["host"]:
                st.caption("Gmail needs a 16-character App Password, not your normal password: "
                           "Google Account > Security > 2-Step Verification > App passwords.")
            return
        failed_now = len(rows) - delivered
        if failed_now:
            st.warning(f"{failed_now} email(s) failed. See the table below and use Retry.")
        if ss.demo_mode:
            st.success(f"Saved {delivered} email(s) with attachments in the **outbox** folder (demo mode, "
                       "nothing was sent over the internet).")
        else:
            st.success(f"Sent {delivered} email(s)." if not test_to else f"Test emails sent to {test_to}. Check your inbox.")

    # ---- delivery mode
    with st.container(border=True):
        a, b = st.columns([2, 1], vertical_alignment="center")
        a.markdown("**Delivery mode**  \n" + (
            '<span class="cf-muted">🧪 Demo: emails are saved as .eml files in the <b>outbox</b> folder. '
            "No password needed. Recipients containing 'bounce' fail on purpose so you can demo retry.</span>"
            if ss.demo_mode else
            f'<span class="cf-muted">📡 Live: sending from <b>{html.escape(cfg["user"] or "not set")}</b> '
            f'via {html.escape(cfg["host"])}.</span>'), unsafe_allow_html=True)
        b.toggle("Demo mode", key="demo_mode")
        if not ss.demo_mode:
            ready = bool(cfg["user"] and cfg["password"])
            with st.expander("Email account " + ("✅ connected" if ready else "⚠️ needs setup"), expanded=not ready):
                st.caption("Best: put these in .streamlit/secrets.toml. Values typed here live only in this "
                           "browser session and are never saved to disk.")
                with st.form("smtp"):
                    c1, c2 = st.columns([3, 1])
                    host = c1.text_input("SMTP host", cfg["host"])
                    port = c2.text_input("Port", str(cfg["port"]))
                    user = st.text_input("Email address", cfg["user"])
                    pw = st.text_input("App password (16 characters for Gmail)", type="password")
                    name = st.text_input("Sender name", cfg["sender_name"])
                    if st.form_submit_button("Save for this session", type="primary"):
                        ss.smtp_session = {"host": host, "port": port, "user": user, "password": pw,
                                           "sender_name": name}
                        st.rerun()

    # ---- test + send side by side
    rows = db.records(ss.batch_ids)
    pending = int((rows.status != "Sent").sum())
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**① Test first**")
            st.text_input("Your email", key="test_email", placeholder="you@example.com")
            if st.button("Send 3 samples to me", width="stretch",
                         disabled=not V.EMAIL_RE.match(ss.test_email or "")):
                send_batch(ss.batch_ids[:3], test_to=ss.test_email)
    with right:
        with st.container(border=True):
            st.markdown("**② Send to students**")
            if not ss.demo_mode:
                st.slider("Seconds between emails (Gmail prefers 1+)", 0.0, 5.0, step=0.5, key="delay")
            st.checkbox("Allow resending to students who already received it", key="allow_resend")
            ok = st.checkbox(f"I've checked the previews and authorise sending to {pending} students")
            if st.button(f"📤 Send {pending} certificates", type="primary", width="stretch",
                         disabled=not ok or pending == 0):
                send_batch(ss.batch_ids)

    # ---- tracking
    st.markdown("#### ③ Delivery status")
    rows = db.records(ss.batch_ids)
    counts = rows.status.value_counts()
    cols = st.columns(5)
    tones = {"Pending": "blue", "Generated": "blue", "Sending": "warn", "Sent": "ok", "Failed": "bad"}
    for col, s in zip(cols, ["Pending", "Generated", "Sending", "Sent", "Failed"]):
        stat(col, s, int(counts.get(s, 0)), tones[s])
    st.write("")
    failed = rows[rows.status == "Failed"]
    if len(failed) and st.button(f"🔁 Retry {len(failed)} failed", type="primary"):
        send_batch(list(failed.cert_id))
        st.rerun()
    order = {"Failed": 0, "Sending": 1, "Pending": 2, "Generated": 3, "Sent": 4}
    rows = rows.assign(_o=rows.status.map(order)).sort_values(["_o", "name"]).drop(columns="_o")
    view = rows.assign(status=rows.status.map(STATUS_LABEL).fillna(rows.status))
    st.dataframe(
        view[["name", "email", "status", "error", "attempts", "sent_at", "cert_id"]], hide_index=True,
        column_config={
            "name": st.column_config.TextColumn("Name", width="medium"),
            "email": st.column_config.TextColumn("Email", width="medium"),
            "status": st.column_config.TextColumn("Status", width="medium"),
            "error": st.column_config.TextColumn("Error", width="medium"),
            "attempts": st.column_config.NumberColumn("Tries", width="small"),
            "sent_at": st.column_config.TextColumn("Sent at", width="small"),
            "cert_id": st.column_config.TextColumn("Certificate ID", width="small"),
        })
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Delivery report (CSV)", rows.drop(columns=["file_path"]).to_csv(index=False),
                       "laureo_report.csv", "text/csv", width="stretch")
    if ss.demo_mode and os.path.isdir(OUTBOX):
        emls = sorted(f for f in os.listdir(OUTBOX) if f.endswith(".eml"))
        if emls:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in emls:
                    z.write(os.path.join(OUTBOX, f), f)
            c2.download_button(f"⬇ Outbox ({len(emls)} emails)", buf.getvalue(), "outbox.zip",
                               "application/zip", width="stretch")

render_status()
