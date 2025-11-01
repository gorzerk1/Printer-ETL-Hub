# adapters/mailer.py
from __future__ import annotations
import os, tempfile, time
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

def send_via_outlook(to_addr: str, subject: str, html_content: str) -> bool:
    try:
        import win32com.client as win32
        try:
            outlook = win32.gencache.EnsureDispatch("Outlook.Application")
        except Exception:
            outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = to_addr
        mail.Subject = subject
        mail.BodyFormat = 2
        mail.HTMLBody = html_content
        mail.Display(False)  # open draft window
        return True
    except Exception:
        return False

def write_eml_draft(to_addr: str, subject: str, html_content: str) -> Path:
    path = Path(tempfile.gettempdir()) / f"ticket_draft_{int(time.time())}.eml"
    msg = EmailMessage(policy=default_policy)
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"
    msg.add_alternative(html_content, subtype="html")
    with open(path, "wb") as f:
        f.write(msg.as_bytes())
    try:
        os.startfile(str(path))  # best effort
    except Exception:
        pass
    return path
