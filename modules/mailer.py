"""Builds personalised emails and sends them over SMTP (Gmail, Outlook, college mail).

Owner: Person C (email + tracking)
Rules covered: 5 (personalised email), 6 (correct attachment), 12 (failures don't stop the batch).
"""
import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from .certificate import fill

try:  # bundled certificates: fixes CERTIFICATE_VERIFY_FAILED on Mac python.org installs
    import certifi
    _CA_FILE = certifi.where()
except ImportError:
    _CA_FILE = None

DEFAULT_SUBJECT = "Congratulations {{NAME}}! Your certificate for {{EVENT}}"
DEFAULT_BODY = """Dear {{NAME}},

Congratulations! You have been recognised for {{ACHIEVEMENT}} at {{EVENT}}. Thank you for your effort and participation.

Your personalised certificate is attached to this email.

Certificate ID: {{CERT_ID}}
Verify it any time: {{VERIFY_URL}}

Warm regards,
{{SENDER_NAME}}"""


def build_message(rec, subject_tpl, body_tpl, sender_email, sender_name, pdf_path, to_override=None):
    """One email for one student, with that student's own certificate attached."""
    body = fill(body_tpl, rec)
    msg = EmailMessage()
    msg["Subject"] = fill(subject_tpl, rec)
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = to_override or rec["EMAIL"]
    msg.set_content(body)
    msg.add_alternative(
        '<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.6;color:#222">'
        + html.escape(body).replace("\n", "<br>")
        + "</div>",
        subtype="html",
    )
    with open(pdf_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf",
                           filename=os.path.basename(pdf_path))
    return msg


class Mailer:
    """Keeps one SMTP connection open for the whole batch and reconnects if it drops."""

    def __init__(self, host, port, user, password):
        self.host, self.port = host, int(port)
        self.user, self.password = user, password
        self.server = None

    def connect(self):
        ctx = ssl.create_default_context(cafile=_CA_FILE)
        if self.port == 465:
            self.server = smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30)
        else:
            self.server = smtplib.SMTP(self.host, self.port, timeout=30)
            self.server.ehlo()
            if self.server.has_extn("starttls"):
                self.server.starttls(context=ctx)
                self.server.ehlo()
        if self.user:
            self.server.login(self.user, self.password)

    def send(self, msg):
        try:
            self.server.send_message(msg)
        except (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError):
            self.connect()  # one reconnect, then let the error surface as a Failed row
            self.server.send_message(msg)

    def close(self):
        try:
            if self.server:
                self.server.quit()
        except Exception:
            pass

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()


class DemoMailer:
    """Demo mode: no login, no internet. Every email is saved as a real .eml file
    (with its PDF attached) in the outbox folder. Double-click one to open it in Mail.

    To demo failure handling, any recipient containing the word 'bounce' is rejected.
    """

    def __init__(self, outbox_dir):
        self.outbox = outbox_dir
        os.makedirs(outbox_dir, exist_ok=True)

    def send(self, msg):
        to = msg["To"]
        if "bounce" in to.lower():
            raise smtplib.SMTPRecipientsRefused({to: (550, b"Mailbox does not exist (demo)")})
        attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
        stem = os.path.splitext(attachments[0])[0] if attachments else "email"
        safe_to = to.replace("@", "_at_").replace("/", "_")
        with open(os.path.join(self.outbox, f"{safe_to}__{stem}.eml"), "wb") as f:
            f.write(bytes(msg))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass
