"""Contacts, email, calls and texts, done the safe way and without any paid API.

- Email: Jarvis writes it and opens it in your mail app; you press Send.
  (Optional: real sending via your own email account's SMTP, always after a "yes".)
- Calls/texts: opened through Windows Phone Link, so your own phone dials.
  You still talk; Jarvis can write you a script with talking points first.
"""
import os
import re
import smtplib
import ssl
import subprocess
import urllib.parse
from email.message import EmailMessage

from . import net, secure
from .skills import skill

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def init_db(memory):
    with memory._lock:
        memory.db.execute("CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, name TEXT, "
                          "phone TEXT, email TEXT, notes TEXT)")
        memory.db.commit()


def _find(memory, who):
    with memory._lock:
        return memory.db.execute(
            "SELECT name, phone, email FROM contacts WHERE lower(name) LIKE ? ORDER BY length(name)",
            (f"%{who.lower().strip()}%",)).fetchall()


def _resolve_email(ctx, to):
    to = to.strip()
    if _EMAIL.match(to):
        return to, to
    hits = [h for h in _find(ctx.memory, to) if h[2]]
    if not hits:
        raise ValueError(f"I don't have an email address for {to}. Add them as a contact first.")
    return hits[0][0], hits[0][2]


def _resolve_phone(ctx, who):
    digits = re.sub(r"[^\d+]", "", who)
    if len(digits) >= 7:
        return who, digits
    hits = [h for h in _find(ctx.memory, who) if h[1]]
    if not hits:
        raise ValueError(f"I don't have a phone number for {who}. Add them as a contact first.")
    return hits[0][0], re.sub(r"[^\d+]", "", hits[0][1])


def smtp_ready(cfg=None) -> bool:
    return secure.has_secret("smtp_password") and bool(secure.get_secret("smtp_user"))


@skill("Save or update a contact (name, phone, email).",
       params={"name": ("string", "Contact name", True), "phone": ("string", "Phone number", False),
               "email": ("string", "Email address", False), "notes": ("string", "Notes", False)})
def add_contact(ctx, name, phone=None, email=None, notes=None):
    if email and not _EMAIL.match(email):
        return "That email address doesn't look right."
    existing = [h for h in _find(ctx.memory, name) if h[0].lower() == name.lower()]
    with ctx.memory._lock:
        if existing:
            ctx.memory.db.execute(
                "UPDATE contacts SET phone=coalesce(?,phone), email=coalesce(?,email), notes=coalesce(?,notes) "
                "WHERE lower(name)=?", (phone, email, notes, name.lower()))
        else:
            ctx.memory.db.execute("INSERT INTO contacts(name, phone, email, notes) VALUES (?,?,?,?)",
                                  (name, phone, email, notes))
        ctx.memory.db.commit()
    return f"{'Updated' if existing else 'Saved'} contact {name}."


@skill("Look up a contact's phone and email.", params={"name": ("string", "Who", True)})
def find_contact(ctx, name):
    hits = _find(ctx.memory, name)
    return "\n".join(f"{n}: phone {p or '-'}, email {e or '-'}" for n, p, e in hits[:5]) or "No such contact."


@skill("EMAIL only: write an email and open it in the user's mail app as a draft to review and send. "
       "Use for emails about scheduling and follow-ups. Not for text messages (use text_message).",
       params={"to": ("string", "Contact name or email address", True),
               "subject": ("string", "Subject line", True),
               "body": ("string", "The full email text, signed with the user's name", True)})
def draft_email(ctx, to, subject, body):
    name, addr = _resolve_email(ctx, to)
    query = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    url = f"mailto:{urllib.parse.quote(addr)}?{query}"
    if len(url) > 1900:  # mailto links have a size limit; put the long body on the clipboard
        subprocess.run(["clip"], input=body, text=True, encoding="utf-16")
        url = f"mailto:{urllib.parse.quote(addr)}?" + urllib.parse.urlencode({"subject": subject},
                                                                            quote_via=urllib.parse.quote)
        os.startfile(url)
        return f"Draft to {name} opened. The body was long, so it's on your clipboard: paste it in, then send."
    os.startfile(url)
    secure.audit("draft_email", {"to": addr, "subject": subject})
    return f"Draft email to {name} <{addr}> is open in your mail app. Review it and press Send."


def _email_preview(ctx, to, subject, body):
    name, addr = _resolve_email(ctx, to)
    return f"send an email from your account to {name} <{addr}>, subject '{subject}', saying: {body[:400]}"


@skill("Send an email immediately from the user's own account (only when they ask to send it now).",
       params={"to": ("string", "Contact name or email address", True),
               "subject": ("string", "Subject line", True),
               "body": ("string", "The full email text", True)},
       risky=True, internet=False, preview=_email_preview, available=smtp_ready)
def send_email(ctx, to, subject, body):
    name, addr = _resolve_email(ctx, to)
    user = secure.get_secret("smtp_user")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, addr, subject
    msg.set_content(body)
    host = net.check_smtp(secure.get_secret("smtp_host") or "smtp.gmail.com", ctx.cfg)
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=20) as s:
        s.login(user, secure.get_secret("smtp_password"))
        s.send_message(msg)
    return f"Email sent to {name}."


def _call_preview(ctx, who):
    name, number = _resolve_phone(ctx, who)
    return f"place a phone call to {name} at {number} through Phone Link"


@skill("Start a phone call through Windows Phone Link (the user's own phone dials, the user talks).",
       params={"who": ("string", "Contact name or phone number", True)},
       risky=True, preview=_call_preview)
def phone_call(ctx, who):
    name, number = _resolve_phone(ctx, who)
    os.startfile(f"tel:{number}")
    return f"Calling {name} through Phone Link."


def _text_preview(ctx, who, message):
    name, number = _resolve_phone(ctx, who)
    return f"open a text to {name} at {number} saying: {message}"


@skill("TEXT/SMS: send a text message to someone's phone through Phone Link. Use whenever the user "
       "says text, message or SMS someone.",
       params={"who": ("string", "Contact name or phone number", True),
               "message": ("string", "The text message", True)},
       risky=True, preview=_text_preview)
def text_message(ctx, who, message):
    name, number = _resolve_phone(ctx, who)
    subprocess.run(["clip"], input=message, text=True, encoding="utf-16")
    try:
        os.startfile(f"sms:{number}?body={urllib.parse.quote(message)}")
    except OSError:
        os.startfile("ms-phone:")
    return f"Text to {name} is ready in Phone Link (also copied to your clipboard). Press send."
