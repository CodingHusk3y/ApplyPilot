"""Hand-picked job intake: collect job links from text, files, or Gmail.

Gmail is read over IMAP with an app password (GMAIL_ADDRESS and
GMAIL_APP_PASSWORD in ~/.applypilot/.env). The mailbox is opened read-only,
so nothing is marked read, moved, or deleted.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import json
import logging
import os
import re
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from applypilot import config

log = logging.getLogger(__name__)

GMAIL_SEEN_PATH = config.APP_DIR / "gmail_seen.json"

_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)

# Links that are never job postings (mail chrome, tracking, assets, etc.)
_SKIP_HOSTS = (
    "google.com", "gstatic.com", "googleusercontent.com", "googleapis.com",
    "licdn.com",  # LinkedIn image/logo CDN
    "schema.org", "w3.org", "fonts.",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
)

# Link shapes that are job postings (used to find the featured job in an email)
_JOB_PATTERNS = re.compile(
    r"linkedin\.com/jobs/view/|indeed\.com/viewjob|greenhouse\.io|lever\.co|ashbyhq\.com|"
    r"myworkdayjobs\.com|icims\.com|smartrecruiters\.com|taleo\.net|/jobs?/|/careers?/|/positions?/",
    re.IGNORECASE,
)
_SKIP_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".js")
_TRACKING_PARAMS = ("utm_", "trk", "refid", "trackingid", "lipi", "eid", "ebp", "recommendedflavor")


def normalize_url(raw: str) -> str | None:
    """Clean one link into a canonical job URL, or None if it is not a job link."""
    url = unescape(raw).rstrip(".,;:!?)]}>'\"")

    # Unwrap Google redirect links (https://www.google.com/url?q=<real url>);
    # every other google.com link (maps, accounts, ...) is skipped below
    parsed = urlparse(url)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q") or parse_qs(parsed.query).get("url")
        if not target:
            return None
        url = target[0]
        parsed = urlparse(url)

    host = parsed.netloc.lower().split(":")[0]
    if not host or any(
        host.startswith(h) if h.endswith(".") else (host == h or host.endswith("." + h))
        for h in _SKIP_HOSTS
    ):
        return None
    if parsed.path.lower().endswith(_SKIP_EXTENSIONS):
        return None
    if "unsubscribe" in url.lower():
        return None
    if parsed.path in ("", "/") and not parsed.query:
        return None  # bare homepage

    # LinkedIn: any form with a job id -> https://www.linkedin.com/jobs/view/<id>
    if "linkedin.com" in host:
        m = re.search(r"/jobs/view/(?:[^/?]*-)?(\d+)", parsed.path)
        job_id = m.group(1) if m else (parse_qs(parsed.query).get("currentJobId") or [None])[0]
        return f"https://www.linkedin.com/jobs/view/{job_id}" if job_id else None

    # Indeed: keep only the job key
    if "indeed.com" in host:
        jk = (parse_qs(parsed.query).get("jk") or parse_qs(parsed.query).get("vjk") or [None])[0]
        return f"https://www.indeed.com/viewjob?jk={jk}" if jk else None

    # Everything else: drop tracking params and fragments
    query = [
        (k, v) for k, vals in parse_qs(parsed.query, keep_blank_values=True).items()
        for v in vals if not k.lower().startswith(_TRACKING_PARAMS)
    ]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def extract_job_urls(text: str) -> list[str]:
    """Find job links in free text or HTML, normalized and de-duplicated in order."""
    seen: set[str] = set()
    urls: list[str] = []
    for raw in _URL_RE.findall(text):
        url = normalize_url(raw)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def split_featured(urls: list[str]) -> tuple[str | None, list[str]]:
    """Split one email's links into (featured job, other links).

    Forwarded job emails (e.g. LinkedIn) put the job named in the subject
    first and append "similar jobs" after it, so the first link that looks
    like a job posting is the one the sender picked.
    """
    featured = next((u for u in urls if _JOB_PATTERNS.search(u)), urls[0] if urls else None)
    return featured, [u for u in urls if u != featured]


def _message_text(msg: email.message.EmailMessage) -> str:
    """All text and HTML parts of an email, concatenated."""
    parts: list[str] = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                parts.append(part.get_content())
            except Exception:
                payload = part.get_payload(decode=True) or b""
                parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _load_seen() -> set[str]:
    try:
        return set(json.loads(GMAIL_SEEN_PATH.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return set()


def mark_gmail_seen(keys: list[str]) -> None:
    """Record emails as processed. Call only after their links are stored."""
    seen = _load_seen() | set(keys)
    GMAIL_SEEN_PATH.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def fetch_gmail_job_urls(sender: str, days: int = 60,
                         include_seen: bool = False) -> tuple[list[str], list[str], list[str]]:
    """Collect job links from emails sent by `sender` in the last `days` days.

    Emails already processed by a previous run are skipped unless
    include_seen is True.

    Returns:
        (featured job per email, other job links found, keys of the emails
        read -- pass to mark_gmail_seen once stored)
    """
    address = os.environ.get("GMAIL_ADDRESS", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not address or not app_password:
        raise RuntimeError(
            "Set GMAIL_ADDRESS (the inbox that receives the links) and GMAIL_APP_PASSWORD "
            f"in {config.ENV_PATH}. Create the app password at "
            "https://myaccount.google.com/apppasswords (requires 2-Step Verification)."
        )

    seen = _load_seen()
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    featured: list[str] = []
    others: list[str] = []
    read_keys: list[str] = []

    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        try:
            imap.login(address, app_password)
        except imaplib.IMAP4.error as e:
            raise RuntimeError(
                f"Gmail login failed for {address}: {e}. Check GMAIL_APP_PASSWORD "
                "(an app password, not your normal password) and that IMAP is on."
            ) from e
        # All Mail includes archived messages; read-only never marks anything read.
        imap.select('"[Gmail]/All Mail"', readonly=True)
        _, data = imap.uid("search", None, f'(FROM "{sender}" SINCE {since})')
        uids = data[0].split() if data and data[0] else []
        log.info("Gmail: %d email(s) from %s in the last %d days", len(uids), sender, days)

        for uid in uids:
            _, msg_data = imap.uid("fetch", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in msg_data if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            key = msg.get("Message-ID") or f"uid:{uid.decode()}"
            if key in seen and not include_seen:
                continue
            pick, rest = split_featured(extract_job_urls(_message_text(msg)))
            log.info("  %s | %s | pick: %s (+%d other)", msg.get("Date", "")[:25],
                     (msg.get("Subject") or "(no subject)")[:45], pick or "none", len(rest))
            if pick and pick not in featured:
                featured.append(pick)
            others.extend(u for u in rest if u not in others)
            read_keys.append(key)
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    # A job featured in one email may appear as a suggestion in another
    others = [u for u in others if u not in featured]
    return featured, others, read_keys
