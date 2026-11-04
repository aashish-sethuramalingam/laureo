"""Reads the student spreadsheet, suggests column mappings and validates every row.

Owner: Person B (data + validation)
Rules covered: 1 (Excel/CSV input), 2 (field mapping), 7 (email selection + fallback),
8 (validation), 13 (duplicate detection).
"""
import difflib
import hashlib
import re
from collections import Counter

import pandas as pd

# Placeholders that can appear on the certificate / in the email, with common column names for each.
PLACEHOLDERS = {
    "NAME": ["name", "student name", "full name", "participant", "participant name", "candidate name"],
    "ID": ["id", "student id", "roll no", "roll number", "roll", "registration number", "reg no", "enrollment no"],
    "EVENT": ["event", "event name", "program", "programme", "workshop", "competition"],
    "ACHIEVEMENT": ["achievement", "award", "position", "rank", "result", "role"],
    "DATE": ["date", "event date", "issue date"],
    "CERT_TYPE": ["certificate type", "cert type", "type", "category"],
}
REQUIRED = {"NAME"}
NONE = "(not in file)"

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
COMMON_DOMAINS = [
    "gmail.com", "yahoo.com", "yahoo.in", "yahoo.co.in", "outlook.com", "outlook.in",
    "hotmail.com", "live.com", "icloud.com", "rediffmail.com", "protonmail.com",
]


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _header_score(cells):
    """How much a row looks like a header row: counts cells such as 'Student Name' or 'Email'."""
    known = {s for syns in PLACEHOLDERS.values() for s in syns}
    score = 0
    for c in cells:
        n = _norm(c)
        if n and (n in known or "mail" in n or "name" in n):
            score += 1
    return score


def _find_header(raw):
    """Index of the header row within the first 20 rows (title rows above it are skipped)."""
    best_row, best_score = 0, -1
    for i in range(min(20, len(raw))):
        s = _header_score(raw.iloc[i].tolist())
        if s > best_score:
            best_row, best_score = i, s
    return best_row, best_score


def load_table(file):
    """Load an uploaded .xlsx/.csv (or a file path) into a DataFrame of clean strings.

    Handles messy real-world files: title rows above the headers, extra sheets
    (instructions, mapping notes) and blank rows. Picks the sheet and row that
    look most like student data. df.attrs["header_row"] is the Excel row number of the headers.
    """
    name = getattr(file, "name", str(file)).lower()
    if name.endswith(".csv"):
        sheets = {"csv": pd.read_csv(file, dtype=str, header=None, keep_default_na=False)}
    else:
        sheets = pd.read_excel(file, dtype=str, header=None, keep_default_na=False, sheet_name=None)

    best = None
    for sheet, raw in sheets.items():
        raw = raw.fillna("")
        if raw.empty:
            continue
        row, score = _find_header(raw)
        if best is None or score > best[2]:
            best = (sheet, raw, score, row)
    if best is None:
        raise ValueError("The file has no data.")
    sheet, raw, _, header_idx = best

    headers, seen = [], Counter()
    for j, h in enumerate(raw.iloc[header_idx].tolist()):
        h = str(h).strip() or f"Column {j + 1}"
        seen[h] += 1
        headers.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = headers
    df = df.apply(lambda col: col.map(lambda v: "" if v is None else str(v).strip()))
    df.index = df.index + 1  # Excel row number of each data row (Excel counts from 1)
    df = df[(df != "").any(axis=1)]  # drop fully empty rows
    df = df.loc[:, [c for c in df.columns if not c.startswith("Column ") or (df[c] != "").any()]]
    df.attrs["sheet"] = sheet
    df.attrs["header_row"] = header_idx + 1
    return df


def email_columns(df):
    """Columns that look like email columns. Student/college/official ones come first."""
    cols = [c for c in df.columns
            if "mail" in _norm(c) and not any(w in _norm(c) for w in ("status", "result", "sent"))]
    if not cols:
        for c in df.columns:
            vals = df[c][df[c] != ""]
            if len(vals) and vals.str.contains("@").mean() > 0.6:
                cols.append(c)
    priority = ("student", "college", "official", "institute", "university")
    cols.sort(key=lambda c: 0 if any(p in _norm(c) for p in priority) else 1)
    return cols


def suggest_mapping(columns):
    """Smart mapping: exact synonym match first, then fuzzy match. Returns {placeholder: column or NONE}."""
    normed = {_norm(c): c for c in columns}
    used, mapping = set(), {}
    for ph, synonyms in PLACEHOLDERS.items():
        choice = None
        for s in synonyms:  # exact match
            if s in normed and normed[s] not in used:
                choice = normed[s]
                break
        if not choice:  # fuzzy match, e.g. "Studnt Name" or "Event Title"
            free = [k for k in normed if normed[k] not in used]
            for s in synonyms:
                hit = difflib.get_close_matches(s, free, n=1, cutoff=0.8)
                if hit:
                    choice = normed[hit[0]]
                    break
        mapping[ph] = choice or NONE
        if choice:
            used.add(choice)
    return mapping


def clean_name(name):
    """Fix spacing and ALL CAPS / all lowercase words: '  PRIYA  sharma ' -> 'Priya Sharma'."""
    words = re.sub(r"\s+", " ", name).strip().split(" ")
    fixed = [w.title() if len(w) > 1 and (w.isupper() or w.islower()) else w for w in words]
    return " ".join(fixed).strip()


def clean_date(value):
    """Excel dates arrive as '2026-11-04 00:00:00'. Turn them into '04 November 2026'."""
    if re.match(r"^\d{4}-\d{2}-\d{2}( 00:00:00)?$", value):
        try:
            return pd.to_datetime(value).strftime("%d %B %Y")
        except Exception:
            return value
    return value


def domain_suggestion(email, known_domains):
    """'priya@gmial.com' -> 'priya@gmail.com'. Returns None if the domain looks fine."""
    local, domain = email.rsplit("@", 1)
    if domain in known_domains:
        return None
    hit = difflib.get_close_matches(domain, list(known_domains), n=1, cutoff=0.8)
    return f"{local}@{hit[0]}" if hit else None


def make_cert_id(rec):
    """Unique, repeatable certificate ID. Same student + same event always gives the same ID."""
    raw = "|".join([rec["EVENT"], rec["ID"], rec["NAME"], rec["EMAIL"]]).lower()
    return "CF-" + hashlib.sha1(raw.encode()).hexdigest()[:10].upper()


def build_records(df, mapping, defaults, primary_email, fallback_email=NONE, autofix_typos=False):
    """Turn spreadsheet rows into validated records.

    Every record gets: ROW (Excel row number), the placeholders, EMAIL, CERT_ID,
    STATUS ('OK' / 'Warning' / 'Error') and ISSUES (plain-language explanation).
    Rows with STATUS 'Error' are never generated or sent.
    """
    email_cols = [c for c in (primary_email, fallback_email) if c and c != NONE and c in df.columns]
    domains = Counter(
        e.split("@")[-1].lower() for c in email_cols for e in df[c] if "@" in e
    )
    # Learn the organisation's own domain: any domain used 3+ times in this file is trusted.
    known = set(COMMON_DOMAINS) | {d for d, n in domains.items() if n >= 3}

    records, seen = [], {}
    for i, row in df.iterrows():
        rec = {"ROW": int(i)}  # Excel row number, matches what organisers see in Excel
        for ph in PLACEHOLDERS:
            col = mapping.get(ph, NONE)
            value = row[col] if col != NONE and col in df.columns else ""
            rec[ph] = value or (defaults.get(ph) or "").strip()
        errors, warnings = [], []

        name = clean_name(rec["NAME"])
        if rec["NAME"] and name != rec["NAME"]:
            warnings.append(f"Name formatted: '{rec['NAME']}' to '{name}'")
        rec["NAME"] = name
        rec["DATE"] = clean_date(rec["DATE"])

        # Rule 7: preferred email, then fallback
        email = row[primary_email].strip() if primary_email in df.columns else ""
        if not EMAIL_RE.match(email) and fallback_email != NONE and fallback_email in df.columns:
            fb = row[fallback_email].strip()
            if EMAIL_RE.match(fb):
                warnings.append("Used fallback email (" + ("primary invalid" if email else "primary empty") + ")")
                email = fb
        email = email.lower()

        if not name:
            errors.append("Missing name")
        if not email:
            errors.append("Missing email")
        elif not EMAIL_RE.match(email):
            errors.append(f"Invalid email '{email}'")
        else:
            fixed = domain_suggestion(email, known)
            if fixed and autofix_typos:
                warnings.append(f"Email typo fixed: {email} to {fixed}")
                email = fixed
            elif fixed:
                errors.append(f"Likely email typo: did you mean {fixed}?")

        for ph in PLACEHOLDERS:
            if ph not in REQUIRED and mapping.get(ph, NONE) != NONE and not rec[ph]:
                warnings.append(f"{ph} is blank")

        # Rule 13: same email + same event twice = duplicate
        if email and not errors:
            key = (email, rec["EVENT"].lower())
            if key in seen:
                errors.append(f"Duplicate of row {seen[key]}")
            else:
                seen[key] = rec["ROW"]

        rec["EMAIL"] = email
        rec["CERT_ID"] = make_cert_id(rec)
        rec["STATUS"] = "Error" if errors else ("Warning" if warnings else "OK")
        rec["ISSUES"] = "; ".join(errors + warnings)
        records.append(rec)

    return pd.DataFrame(records)
