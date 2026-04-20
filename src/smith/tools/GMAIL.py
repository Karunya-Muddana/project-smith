"""
GMAIL TOOL — Smith Agent Runtime
---------------------------------
Supports: read_inbox, read_email, send_email, reply, forward,
          star, mark_read, trash, search, list_labels

Auth: Google OAuth2 (one-time browser flow, token auto-refreshes)
Credentials: .smith_gmail/credentials.json  ← download from Google Cloud Console
Token cache: .smith_gmail/token.json        ← auto-created on first run

On first use, a browser window opens to authorize Smith.
After that, the token auto-refreshes — no sign-in needed.
"""

from __future__ import annotations

import base64
import logging
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smith.gmail")

# ─────────────────────────────────────────────────────────────────────────────
# Auth + credentials paths
# ─────────────────────────────────────────────────────────────────────────────

# Absolute path of the .smith_gmail dir — always anchored to the project root
# derived from this file's location, never from CWD.
_THIS_FILE  = Path(__file__).resolve()        # .../src/smith/tools/GMAIL.py
_TOOLS_DIR  = _THIS_FILE.parent               # .../src/smith/tools/
_SRC_DIR    = _TOOLS_DIR.parent.parent        # .../src/
_PROJECT_DIR = _SRC_DIR.parent               # .../project-smith/  (contains pyproject.toml)
_GMAIL_DIR  = _PROJECT_DIR / ".smith_gmail"
_GMAIL_DIR.mkdir(parents=True, exist_ok=True)

logger.info(f"Gmail: using credentials dir: {_GMAIL_DIR}")

def _gmail_dir() -> Path:
    """Return absolute path to the .smith_gmail credentials directory."""
    return _GMAIL_DIR

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

_SETUP_GUIDE = (
    "Gmail tool setup required:\n"
    "1. Go to https://console.cloud.google.com\n"
    "2. Enable the Gmail API\n"
    "3. Create OAuth 2.0 credentials (Desktop app)\n"
    "4. Download credentials.json\n"
    "5. Place it at: {creds_path}\n"
    "6. Run any Gmail command — a browser will open to authorize Smith\n"
    "7. Token is saved automatically — one-time setup only"
)


def _get_gmail_service():
    """
    Return authenticated Gmail API service.
    On first run: opens browser for OAuth consent.
    On subsequent runs: auto-refreshes token silently.
    Raises RuntimeError with setup instructions if credentials missing.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Missing Google API packages. Install with:\n"
            "pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )

    gmail_dir   = _gmail_dir()
    creds_file  = gmail_dir / "credentials.json"
    token_file  = gmail_dir / "token.json"

    if not creds_file.exists():
        raise RuntimeError(
            _SETUP_GUIDE.format(creds_path=str(creds_file))
        )

    # Check for un-filled placeholder secret
    try:
        import json as _json
        _raw_creds = _json.loads(creds_file.read_text())
        _secret = (
            _raw_creds.get("installed", _raw_creds.get("web", {}))
            .get("client_secret", "")
        )
        if "REPLACE" in _secret or not _secret:
            raise RuntimeError(
                "credentials.json still has a placeholder client_secret.\n"
                "Fix:\n"
                "1. Go to https://console.cloud.google.com/apis/credentials\n"
                "2. Click your OAuth 2.0 Client ID\n"
                "3. Copy the 'Client Secret' (starts with GOCSPX-)\n"
                f"4. Open {creds_file}\n"
                "5. Replace 'REPLACE_WITH_YOUR_CLIENT_SECRET' with the real secret\n"
                "   OR download the full credentials.json from Google and replace the file."
            )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Could not read credentials.json: {e}")

    creds = None

    # Load existing token
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)
        except Exception as e:
            logger.warning(f"Gmail: token.json invalid, will re-authorize: {e}")
            creds = None

    # Refresh or re-authorize
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Gmail: refreshing expired token...")
            creds.refresh(Request())
        else:
            logger.info("Gmail: opening browser for OAuth authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), _SCOPES)
            creds = flow.run_local_server(port=0)

        # Save refreshed/new token
        try:
            with open(token_file, "w") as f:
                f.write(creds.to_json())
            logger.info(f"Gmail: token saved to {token_file}")
        except Exception as e:
            logger.error(f"Gmail: FAILED to save token to {token_file}: {e}")

    return build("gmail", "v1", credentials=creds)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(
                    part["body"]["data"]
                ).decode("utf-8", errors="replace")
        # Fallback to HTML part
        for part in payload["parts"]:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                raw = base64.urlsafe_b64decode(
                    part["body"]["data"]
                ).decode("utf-8", errors="replace")
                # Strip HTML tags
                import re
                return re.sub(r"<[^>]+>", "", raw).strip()
    return ""


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _clean_email_body(body: str) -> str:
    """
    Post-process email body to remove non-email content.
    
    When an LLM generates email content, it sometimes includes research
    summaries, data tables, or other context ABOVE the actual email.
    This function detects and extracts only the email portion.
    """
    import re

    if not body or not isinstance(body, str):
        return body or ""

    # Strip any raw {{STEPS.N...}} template placeholders
    body = re.sub(r"\{\{\s*STEPS\.\d+[^}]*\}\}", "", body)

    # Detect email start markers (salutations)
    email_start_patterns = [
        r"(?:^|\n)\s*(?:Dear|Hi|Hello|Hey)\s+\w+",          # "Dear Kevin,"
        r"(?:^|\n)\s*Subject:\s*.+(?:\n|$)",                  # "Subject: ..."
        r"(?:^|\n)\s*(?:To|From):\s*.+(?:\n|$)",             # "To: ..."
    ]

    # Detect email end markers (closings)
    email_end_patterns = [
        r"(?:Take care|Best regards|Sincerely|Kind regards|Warm regards|Yours|With love|Cheers)",
        r"\[Your (?:Name|name)\]",
        r"(?:Regards|Thanks|Thank you),?\s*$",
    ]

    # Try to find email content boundaries
    best_start = None
    for pattern in email_start_patterns:
        m = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
        if m:
            if best_start is None or m.start() < best_start:
                best_start = m.start()
            break  # Use first matching salutation pattern

    if best_start is not None and best_start > 50:
        # There's significant content BEFORE the email salutation — strip it
        email_portion = body[best_start:].strip()

        # Verify the extracted portion still looks like an email
        # (has at least 100 chars and contains some closing-like text)
        has_closing = any(
            re.search(p, email_portion, re.IGNORECASE | re.MULTILINE)
            for p in email_end_patterns
        )

        if len(email_portion) > 100 and has_closing:
            body = email_portion

    # Clean up markdown formatting for plaintext email
    # Bold: **text** or __text__ → text
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = re.sub(r"__(.+?)__", r"\1", body)
    # Italic: *text* or _text_ → text (careful not to hit bullet points)
    body = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"\1", body)
    # Headers: ### text → text
    body = re.sub(r"^#{1,6}\s+", "", body, flags=re.MULTILINE)
    # Bullet points: - text → text (keep the dash for readability)
    # Horizontal rules: --- → (remove)
    body = re.sub(r"^-{3,}\s*$", "", body, flags=re.MULTILINE)
    # Links: [text](url) → text (url)
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", body)

    # Clean up excessive whitespace
    body = re.sub(r"\n{3,}", "\n\n", body)

    return body.strip()


def _make_message(to: str, subject: str, body: Any,
                  reply_to_id: str = None, service=None) -> dict:
    """Build a MIME email and encode it for the Gmail API."""
    import json
    
    # The orchestrator sometimes passes dicts as the body.
    # Extract the actual text content instead of dumping JSON.
    if isinstance(body, dict):
        # Look for common text fields from other tools/agents
        body_str = (
            body.get("response") or 
            body.get("content") or 
            body.get("text") or 
            body.get("body")
        )
        if not body_str:
            import json
            body_str = json.dumps(body, indent=2)
    else:
        body_str = str(body)
        
    msg = MIMEMultipart()
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_str, "plain"))

    # Threading headers for replies/forwards
    if reply_to_id and service:
        try:
            orig = service.users().messages().get(
                userId="me", id=reply_to_id, format="metadata",
                metadataHeaders=["Message-ID", "Subject", "References"]
            ).execute()
            orig_headers = orig.get("payload", {}).get("headers", [])
            orig_msg_id  = _header(orig_headers, "Message-ID")
            orig_refs    = _header(orig_headers, "References")
            if orig_msg_id:
                msg["In-Reply-To"] = orig_msg_id
                msg["References"]  = (orig_refs + " " + orig_msg_id).strip()
            msg["threadId"] = orig.get("threadId", "")
        except Exception:
            pass

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


# ─────────────────────────────────────────────────────────────────────────────
# Operations
# ─────────────────────────────────────────────────────────────────────────────

def _read_inbox(service, max_results: int = 10, label: str = "INBOX") -> dict:
    """List recent emails from inbox (or any label)."""
    res = service.users().messages().list(
        userId="me", labelIds=[label], maxResults=max_results
    ).execute()

    messages = res.get("messages", [])
    if not messages:
        return {"status": "success", "emails": [], "count": 0, "label": label}

    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date", "To"]
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        emails.append({
            "id":       msg["id"],
            "thread":   msg.get("threadId"),
            "subject":  _header(headers, "Subject") or "(no subject)",
            "from":     _header(headers, "From"),
            "to":       _header(headers, "To"),
            "date":     _header(headers, "Date"),
            "snippet":  msg.get("snippet", ""),
            "labels":   msg.get("labelIds", []),
            "unread":   "UNREAD" in msg.get("labelIds", []),
        })

    return {"status": "success", "emails": emails, "count": len(emails), "label": label}


def _read_email(service, message_id: str) -> dict:
    """Read the full body of a specific email."""
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = msg.get("payload", {}).get("headers", [])
    body    = _decode_body(msg.get("payload", {}))

    return {
        "status":   "success",
        "id":       msg["id"],
        "thread":   msg.get("threadId"),
        "subject":  _header(headers, "Subject"),
        "from":     _header(headers, "From"),
        "to":       _header(headers, "To"),
        "date":     _header(headers, "Date"),
        "body":     body[:10_000],  # cap at 10K chars
        "labels":   msg.get("labelIds", []),
    }


def _send_email(service, to: str, subject: str, body: str) -> dict:
    """Send a new email."""
    body = _clean_email_body(body)
    message  = _make_message(to, subject, body)
    sent     = service.users().messages().send(userId="me", body=message).execute()
    return {
        "status":     "success",
        "action":     "sent",
        "message_id": sent.get("id"),
        "to":         to,
        "subject":    subject,
    }


def _reply(service, message_id: str, body: str) -> dict:
    """Reply to an email thread."""
    body = _clean_email_body(body)
    orig    = service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["Subject", "From", "To"]
    ).execute()
    orig_h  = orig.get("payload", {}).get("headers", [])
    orig_from = _header(orig_h, "From")
    orig_sub  = _header(orig_h, "Subject")
    re_sub    = orig_sub if orig_sub.lower().startswith("re:") else f"Re: {orig_sub}"

    message = _make_message(orig_from, re_sub, body, reply_to_id=message_id, service=service)
    message["threadId"] = orig.get("threadId", "")
    sent = service.users().messages().send(userId="me", body=message).execute()
    return {
        "status":       "success",
        "action":       "replied",
        "message_id":   sent.get("id"),
        "replied_to":   message_id,
        "to":           orig_from,
        "subject":      re_sub,
    }


def _forward(service, message_id: str, to: str, note: str = "") -> dict:
    """Forward an email to a new recipient with an optional note."""
    orig = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    orig_h   = orig.get("payload", {}).get("headers", [])
    orig_sub = _header(orig_h, "Subject")
    orig_from= _header(orig_h, "From")
    orig_date= _header(orig_h, "Date")
    orig_body= _decode_body(orig.get("payload", {}))

    fwd_body = (
        f"{note}\n\n---------- Forwarded message ----------\n"
        f"From: {orig_from}\nDate: {orig_date}\n"
        f"Subject: {orig_sub}\n\n{orig_body}"
    )
    fwd_sub  = orig_sub if orig_sub.lower().startswith("fwd:") else f"Fwd: {orig_sub}"
    message  = _make_message(to, fwd_sub, fwd_body)
    sent     = service.users().messages().send(userId="me", body=message).execute()
    return {
        "status":       "success",
        "action":       "forwarded",
        "message_id":   sent.get("id"),
        "forwarded_to": to,
        "subject":      fwd_sub,
    }


def _modify_labels(service, message_id: str, add: list = None, remove: list = None) -> dict:
    """Add or remove Gmail labels from a message."""
    body = {}
    if add:    body["addLabelIds"]    = add
    if remove: body["removeLabelIds"] = remove
    service.users().messages().modify(userId="me", id=message_id, body=body).execute()
    return {"status": "success", "message_id": message_id, "add": add, "remove": remove}


def _trash(service, message_id: str) -> dict:
    """Move a message to trash."""
    service.users().messages().trash(userId="me", id=message_id).execute()
    return {"status": "success", "action": "trashed", "message_id": message_id}


def _search(service, query: str, max_results: int = 10) -> dict:
    """Search emails using Gmail query syntax (e.g. 'from:boss@co.com is:unread')."""
    res = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = res.get("messages", [])
    results  = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        h = msg.get("payload", {}).get("headers", [])
        results.append({
            "id":      msg["id"],
            "subject": _header(h, "Subject") or "(no subject)",
            "from":    _header(h, "From"),
            "date":    _header(h, "Date"),
            "snippet": msg.get("snippet", ""),
            "unread":  "UNREAD" in msg.get("labelIds", []),
        })

    return {"status": "success", "query": query, "results": results, "count": len(results)}


def _list_labels(service) -> dict:
    """Return all labels/folders in the mailbox."""
    res    = service.users().labels().list(userId="me").execute()
    labels = [{"id": l["id"], "name": l["name"]} for l in res.get("labels", [])]
    return {"status": "success", "labels": labels}


# ─────────────────────────────────────────────────────────────────────────────
# Main Smith entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_gmail_tool(
    operation:   str,
    to:          Optional[str] = None,
    subject:     Optional[str] = None,
    body:        Optional[str] = None,
    message_id:  Optional[str] = None,
    query:       Optional[str] = None,
    max_results: int            = 10,
    label:       str            = "INBOX",
    star:        Optional[bool] = None,
    mark_read:   Optional[bool] = None,
    note:        str            = "",
) -> dict:
    """
    Gmail tool for Smith.

    operation options:
      read_inbox   — list recent emails (max_results, label)
      read_email   — full body of one email (message_id)
      send_email   — send email (to, subject, body)
      reply        — reply to email (message_id, body)
      forward      — forward email (message_id, to, note)
      star         — star/unstar email (message_id, star=True/False)
      mark_read    — mark read/unread (message_id, mark_read=True/False)
      trash        — move to trash (message_id)
      search       — search emails (query, max_results)
      list_labels  — list all labels/folders
    """
    try:
        service = _get_gmail_service()
    except RuntimeError as e:
        return {
            "status": "error",
            "error":  str(e),
            "setup_required": True,
        }

    try:
        op = (operation or "").lower().strip()

        if op == "read_inbox":
            return _read_inbox(service, max_results=max_results, label=label)

        elif op == "read_email":
            if not message_id:
                return {"status": "error", "error": "'message_id' is required for read_email"}
            return _read_email(service, message_id)

        elif op == "send_email":
            if not all([to, subject, body]):
                return {"status": "error", "error": "'to', 'subject', 'body' are all required for send_email"}
            return _send_email(service, to, subject, body)

        elif op == "reply":
            if not message_id or not body:
                return {"status": "error", "error": "'message_id' and 'body' are required for reply"}
            return _reply(service, message_id, body)

        elif op == "forward":
            if not message_id or not to:
                return {"status": "error", "error": "'message_id' and 'to' are required for forward"}
            return _forward(service, message_id, to, note=note)

        elif op == "star":
            if not message_id:
                return {"status": "error", "error": "'message_id' is required for star"}
            if star is True:
                return _modify_labels(service, message_id, add=["STARRED"])
            else:
                return _modify_labels(service, message_id, remove=["STARRED"])

        elif op == "mark_read":
            if not message_id:
                return {"status": "error", "error": "'message_id' is required for mark_read"}
            if mark_read is True:
                return _modify_labels(service, message_id, remove=["UNREAD"])
            else:
                return _modify_labels(service, message_id, add=["UNREAD"])

        elif op == "trash":
            if not message_id:
                return {"status": "error", "error": "'message_id' is required for trash"}
            return _trash(service, message_id)

        elif op == "search":
            if not query:
                return {"status": "error", "error": "'query' is required for search"}
            return _search(service, query, max_results=max_results)

        elif op == "list_labels":
            return _list_labels(service)

        else:
            return {
                "status": "error",
                "error":  f"Unknown operation '{op}'. Valid: read_inbox, read_email, send_email, reply, forward, star, mark_read, trash, search, list_labels"
            }

    except Exception as e:
        logger.exception(f"Gmail tool error: {e}")
        return {"status": "error", "error": str(e)}


# Alias for Smith runtime
gmail = run_gmail_tool


# ─────────────────────────────────────────────────────────────────────────────
# Smith Tool Metadata
# ─────────────────────────────────────────────────────────────────────────────

METADATA = {
    "name":        "gmail",
    "description": (
        "Gmail integration: read inbox, read full emails, send emails, reply, "
        "forward, star, mark as read/unread, trash, and search using Gmail query syntax. "
        "Requires one-time OAuth2 browser authorization (credentials.json in .smith_gmail/). "
        "Use 'read_inbox' to list emails, 'send_email' to compose, 'reply' to respond to a thread, "
        "'search' for Gmail query syntax like 'from:boss@company.com is:unread'."
    ),
    "function":    "run_gmail_tool",
    "dangerous":   True,   # Can send email — Smith will require explicit user confirmation
    "domain":      "communication",
    "output_type": "structured",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type":        "string",
                "description": "One of: read_inbox, read_email, send_email, reply, forward, star, mark_read, trash, search, list_labels",
                "enum":        ["read_inbox", "read_email", "send_email", "reply", "forward",
                                "star", "mark_read", "trash", "search", "list_labels"]
            },
            "to":          {"type": "string", "description": "Recipient email address (for send_email, forward)"},
            "subject":     {"type": "string", "description": "Email subject (for send_email)"},
            "body":        {"type": "string", "description": "Email body text (for send_email, reply)"},
            "message_id":  {"type": "string", "description": "Gmail message ID (from read_inbox results)"},
            "query":       {"type": "string", "description": "Gmail search query, e.g. 'from:user@example.com is:unread'"},
            "max_results": {"type": "integer", "default": 10, "description": "Max emails to return"},
            "label":       {"type": "string",  "default": "INBOX", "description": "Gmail label (INBOX, SENT, DRAFTS, SPAM, etc.)"},
            "star":        {"type": "boolean", "description": "True = star, False = unstar (for 'star' operation)"},
            "mark_read":   {"type": "boolean", "description": "True = mark read, False = mark unread"},
            "note":        {"type": "string",  "default": "", "description": "Optional note prepended when forwarding"},
        },
        "required": ["operation"]
    }
}
