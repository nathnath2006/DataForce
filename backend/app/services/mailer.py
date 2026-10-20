"""Outgoing email over SMTP (Gmail with an App Password, STARTTLS required).

`send_async` runs `send` on a small bounded thread pool, so a slow SMTP server never delays
a request.
When SMTP is not configured nothing is sent: the caller keeps its log fallback. The password and
the message text never reach a log or an error; failures log only the exception type.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formataddr

import certifi

from app.config import Settings

log = logging.getLogger(__name__)

TIMEOUT_S = 10
MAX_PER_HOUR = 60  # global per-process cap; the excess is dropped, not queued
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mailer")
_sent_at: deque[float] = deque()
_cap_lock = threading.Lock()


def is_configured(settings: Settings) -> bool:
    password = settings.smtp_password.get_secret_value() if settings.smtp_password else ""
    return bool(settings.smtp_username.strip() and password)


def _clean(value: str, what: str) -> str:
    value = value.strip()
    if not value or "\r" in value or "\n" in value or "\0" in value:
        raise ValueError(f"invalid {what}")
    return value


def _build(settings: Settings, to: str, subject: str, text: str, html: str | None) -> EmailMessage:
    to = _clean(to, "recipient")
    if "@" not in to or "," in to or ";" in to or " " in to or "<" in to or len(to) > 320:
        raise ValueError("invalid recipient")  # exactly one plain address: no relay, no injection
    sender = _clean(settings.mail_from or settings.smtp_username, "sender")
    msg = EmailMessage()
    msg["From"] = formataddr((_clean(settings.mail_from_name, "sender name"), sender))
    msg["To"] = to
    msg["Subject"] = _clean(subject, "subject")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def send(settings: Settings, to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one email now. True when the server accepted it; False when SMTP is off or failed."""
    if not is_configured(settings):
        log.warning("Email not sent: SMTP is not configured")
        return False
    try:
        msg = _build(settings, to, subject, text, html)
        assert settings.smtp_password is not None
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_S) as smtp:
            # certifi's CA bundle: python.org builds on macOS ship without system certificates.
            smtp.starttls(context=ssl.create_default_context(cafile=certifi.where()))
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - never put the message or credentials in a log
        log.warning("Email not sent (%s)", type(exc).__name__)
        return False
    return True


def _allow() -> bool:
    now = time.monotonic()
    with _cap_lock:
        while _sent_at and now - _sent_at[0] > 3600:
            _sent_at.popleft()
        if len(_sent_at) >= MAX_PER_HOUR:
            return False
        _sent_at.append(now)
        return True


def send_async(
    settings: Settings, to: str, subject: str, text: str, html: str | None = None
) -> bool:
    """Hand one email to the bounded sender pool (2 workers, 60 per hour per process). True means
    accepted for sending, not delivered; over the cap the email is dropped with a warning."""
    if not _allow():
        log.warning("Email dropped: hourly cap reached")
        return False
    _executor.submit(send, settings, to, subject, text, html)
    return True
