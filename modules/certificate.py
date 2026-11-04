"""Draws personalised certificates on a template image and saves them as PDFs.

Owner: Person A (certificates)
Rules covered: 3 (one certificate per student), 4 (template with placeholders), 14 (file naming).
"""
import os
import re

from PIL import Image, ImageDraw, ImageFont

try:
    import qrcode
except ImportError:  # QR is an optional extra; the app still works without it
    qrcode = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(BASE, "assets", "fonts")
FONT_FILES = {
    "name": "DejaVuSerif-Bold.ttf",   # student name (swap in any .ttf you like, same filename)
    "bold": "DejaVuSans-Bold.ttf",
    "regular": "DejaVuSans.ttf",
}

DEFAULT_LAYOUT = {
    "name_y": 0.47, "name_size": 0.075,
    "body_y": 0.585, "body_size": 0.03,
    "footer_y": 0.905,
    "color": "#1E3A8A",
    "qr": True, "qr_x": 0.85, "qr_y": 0.78, "qr_size": 0.15,
}
DEFAULT_BODY = "in recognition of {{ACHIEVEMENT}} at {{EVENT}}, {{DATE}}."

_font_cache = {}


def get_font(kind, size):
    size = max(int(size), 8)
    key = (kind, size)
    if key not in _font_cache:
        path = os.path.join(FONT_DIR, FONT_FILES[kind])
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _font_cache[key] = ImageFont.load_default(size=size)
    return _font_cache[key]


def fill(text, rec):
    """Replace {{PLACEHOLDER}} with values from the record. Unknown placeholders become blank."""
    out = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(rec.get(m.group(1).upper(), "")), text)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def default_template(width=2000, height=1414):
    """Built-in A4-landscape template so the team never depends on an external design."""
    navy, gold, grey = (30, 58, 138), (201, 162, 39), (80, 80, 80)
    img = Image.new("RGB", (width, height), (253, 251, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, width - 40, height - 40], outline=navy, width=14)
    d.rectangle([75, 75, width - 75, height - 75], outline=gold, width=4)
    d.text((width / 2, height * 0.17), "CERTIFICATE", font=get_font("name", 110), fill=navy, anchor="mm")
    d.text((width / 2, height * 0.25), "OF ACHIEVEMENT", font=get_font("bold", 44), fill=gold, anchor="mm")
    d.text((width / 2, height * 0.36), "This certificate is proudly presented to",
           font=get_font("regular", 40), fill=grey, anchor="mm")
    d.line([width * 0.12, height * 0.80, width * 0.35, height * 0.80], fill=grey, width=3)
    d.text((width * 0.235, height * 0.83), "Event Organizer", font=get_font("regular", 32), fill=grey, anchor="mm")
    return img


def _wrap(text, font, draw, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render(template, rec, layout, body_text, verify_url=None):
    """Return a new image: template + this student's details. Never edits the template itself."""
    img = template.convert("RGB").copy()
    W, H = img.size
    d = ImageDraw.Draw(img)

    # Student name, auto-shrinks so long names never overflow
    size = int(H * layout["name_size"])
    font = get_font("name", size)
    while d.textlength(rec["NAME"], font=font) > W * 0.8 and size > 20:
        size -= 4
        font = get_font("name", size)
    d.text((W / 2, H * layout["name_y"]), rec["NAME"], font=font, fill=layout["color"], anchor="mm")

    # Body line(s) with placeholders filled in
    body_size = int(H * layout["body_size"])
    body_font = get_font("regular", body_size)
    y = H * layout["body_y"]
    for line in _wrap(fill(body_text, rec), body_font, d, W * 0.72):
        d.text((W / 2, y), line, font=body_font, fill=(55, 55, 55), anchor="mm")
        y += body_size * 1.45

    # Certificate ID footer (also printed in the email, so student and organiser can match them)
    d.text((W / 2, H * layout["footer_y"]), f"Certificate ID: {rec['CERT_ID']}",
           font=get_font("regular", H * 0.018), fill=(110, 110, 110), anchor="mm")

    # QR code for verification
    if layout.get("qr") and verify_url and qrcode:
        qr = qrcode.QRCode(border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        q_img = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
        s = int(H * layout["qr_size"])
        q_img = q_img.resize((s, s), Image.NEAREST)
        x, yq = int(W * layout["qr_x"] - s / 2), int(H * layout["qr_y"] - s / 2)
        img.paste(q_img, (x, yq))
        d.text((x + s / 2, yq + s + H * 0.015), "Scan to verify",
               font=get_font("regular", H * 0.014), fill=(110, 110, 110), anchor="mm")
    return img


def slug(text, limit=30):
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")
    return text[:limit] or "NA"


def file_name(rec):
    """Rule 14: Event_StudentID_Name_CertID.pdf. The certificate ID makes every file unique."""
    return f"{slug(rec['EVENT'])}_{slug(rec['ID'])}_{slug(rec['NAME'])}_{rec['CERT_ID']}.pdf"


def save_pdf(img, path, rec):
    """Save as PDF. The certificate ID is also stored inside the PDF metadata."""
    img.save(path, "PDF", resolution=150, title=f"Certificate for {rec['NAME']}",
             subject=rec["CERT_ID"], author="Laureo")
