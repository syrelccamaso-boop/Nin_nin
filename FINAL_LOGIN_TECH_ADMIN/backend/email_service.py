"""
Centrum Laboratory - outgoing email (Brevo transactional API).

This is the ONLY place in the project that talks to Brevo. The Streamlit
frontend never sends email itself; it calls the FastAPI backend, which calls
the functions below.

Required .env values (placeholders only - never commit real values):

    BREVO_API_KEY=your_api_key
    BREVO_SENDER_EMAIL=your_verified_email@example.com
    BREVO_SENDER_NAME=Computer Laboratory Monitoring System

BREVO_SENDER_EMAIL must be a sender you have verified in Brevo
(Settings > Senders, Domains, IPs > Senders), or an address on a domain you
have authenticated there.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from pathlib import Path

import sib_api_v3_sdk
from dotenv import find_dotenv, load_dotenv
from sib_api_v3_sdk.rest import ApiException

logger = logging.getLogger("centrum.email")


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================
# load_dotenv() with no arguments only searches upward from the *calling
# file's* folder, so a .env sitting in a sibling folder (or wherever you
# happen to start uvicorn) can be silently missed. Look in the obvious places
# explicitly. Existing environment variables are never overwritten.

_HERE = Path(__file__).resolve().parent

for _candidate in (_HERE / ".env", _HERE.parent / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate)

load_dotenv(find_dotenv(usecwd=True))


# =========================================================
# SETTINGS
# =========================================================

DEFAULT_SENDER_NAME = "Computer Laboratory Monitoring System"

CODE_TTL_MINUTES = 10

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Values copied from examples that must never be used as a real sender.
_PLACEHOLDER_SENDERS = {
    "your_verified_email@example.com",
    "your_verified_sender_email",
    "you@example.com",
}


# =========================================================
# ERRORS
# =========================================================


class EmailConfigError(RuntimeError):
    """The .env configuration for Brevo is missing or invalid."""


class EmailSendError(RuntimeError):
    """Brevo refused the email or could not be reached.

    str(error) is a short message that is safe to show to end users.
    """


# =========================================================
# CONFIGURATION
# =========================================================


def _clean(value: str | None) -> str:
    """Strip whitespace and one pair of surrounding quotes from an env value."""

    value = (value or "").strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()

    return value


def email_config_problems() -> list[str]:
    """Describe what is wrong with the Brevo settings (never includes values)."""

    problems = []

    api_key = _clean(os.getenv("BREVO_API_KEY"))
    sender_email = _clean(os.getenv("BREVO_SENDER_EMAIL"))

    if not api_key:
        problems.append("BREVO_API_KEY is missing from .env.")

    if not sender_email:
        problems.append("BREVO_SENDER_EMAIL is missing from .env.")

    elif sender_email.lower() in _PLACEHOLDER_SENDERS:
        problems.append("BREVO_SENDER_EMAIL still contains a placeholder value.")

    elif not _EMAIL_REGEX.match(sender_email):
        problems.append("BREVO_SENDER_EMAIL is not a valid email address.")

    return problems


def get_email_config() -> dict:
    """Return the cleaned Brevo settings or raise EmailConfigError."""

    problems = email_config_problems()

    if problems:
        raise EmailConfigError(" ".join(problems))

    return {
        "api_key": _clean(os.getenv("BREVO_API_KEY")),
        "sender_email": _clean(os.getenv("BREVO_SENDER_EMAIL")),
        "sender_name": (_clean(os.getenv("BREVO_SENDER_NAME")) or DEFAULT_SENDER_NAME),
    }


# Warn once at startup instead of crashing the whole API on import.
for _problem in email_config_problems():
    logger.warning("Email configuration: %s", _problem)


# =========================================================
# BREVO CLIENT
# =========================================================

_api_cache: dict = {}


def _get_api(api_key: str) -> sib_api_v3_sdk.TransactionalEmailsApi:

    api = _api_cache.get(api_key)

    if api is None:

        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key["api-key"] = api_key

        api = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        _api_cache.clear()
        _api_cache[api_key] = api

    return api


def _brevo_error_details(error: ApiException) -> tuple[str, str]:
    """Pull Brevo's error code and message out of the HTTP body."""

    try:
        body = json.loads(error.body or "{}")
        return str(body.get("code", "")), str(body.get("message", ""))

    except (TypeError, ValueError):
        return "", ""


def _friendly_message(status: int | None, code: str, message: str) -> str:
    """Turn a Brevo failure into a short message for the end user."""

    text = f"{code} {message}".lower()

    if status == 401 or "key not found" in text or "unauthorized" in text:
        return (
            "The email service is not configured correctly. "
            "Please contact the administrator."
        )

    if "sender" in text:
        return (
            "The email sender is not set up or not verified. "
            "Please contact the administrator."
        )

    if status == 429:
        return "Too many emails were sent. Please wait a moment and try again."

    return "We couldn't send the email right now. Please try again later."


def _send_email(
    recipient_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    recipient_name: str = "",
) -> None:

    try:
        config = get_email_config()

    except EmailConfigError as error:

        # Details go to the server log only.
        logger.error("Email not sent - %s", error)

        raise EmailSendError(
            "The email service is not configured. " "Please contact the administrator."
        ) from None

    sender = sib_api_v3_sdk.SendSmtpEmailSender(
        email=config["sender_email"],
        name=config["sender_name"],
    )

    recipient = sib_api_v3_sdk.SendSmtpEmailTo(
        email=recipient_email,
        name=recipient_name or None,
    )

    message = sib_api_v3_sdk.SendSmtpEmail(
        sender=sender,
        to=[recipient],
        subject=subject,
        html_content=html_content,
        text_content=text_content,
    )

    try:

        _get_api(config["api_key"]).send_transac_email(message)

        logger.info("Email '%s' sent to %s", subject, recipient_email)

    except ApiException as error:

        code, brevo_message = _brevo_error_details(error)

        # Never log headers or the API key - only Brevo's code and message.
        logger.error(
            "Brevo rejected the email (status=%s, code=%s): %s",
            error.status,
            code or "-",
            brevo_message or "-",
        )

        raise EmailSendError(
            _friendly_message(error.status, code, brevo_message)
        ) from None

    except Exception as error:

        logger.error(
            "Could not reach Brevo: %s",
            type(error).__name__,
        )

        raise EmailSendError(
            "We couldn't reach the email service. Please try again later."
        ) from None


def _email_layout(greeting: str, intro: str, code: str, footer: str) -> str:

    sender_name = html.escape(
        _clean(os.getenv("BREVO_SENDER_NAME")) or DEFAULT_SENDER_NAME
    )

    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #111827;">
            <h2>{sender_name}</h2>

            <p>{greeting}</p>

            <p>{intro}</p>

            <h1 style="letter-spacing: 8px;">{code}</h1>

            <p>This code will expire in {CODE_TTL_MINUTES} minutes.</p>

            <p>{footer}</p>

            <p>&mdash; {sender_name}</p>
        </body>
    </html>
    """


# =========================================================
# SEND VERIFICATION CODE
# =========================================================


def send_verification_email(
    recipient_email: str,
    code: str,
    first_name: str = "",
) -> None:
    """Email the 6-digit sign-up verification code. Raises EmailSendError."""

    name = html.escape(first_name.strip())
    greeting = f"Hello {name}," if name else "Hello,"

    _send_email(
        recipient_email=recipient_email,
        recipient_name=first_name.strip(),
        subject="Centrum Laboratory - Email Verification Code",
        html_content=_email_layout(
            greeting=greeting,
            intro="Your email verification code is:",
            code=html.escape(code),
            footer="If you did not request this code, you can ignore this email.",
        ),
        text_content=(
            f"{greeting}\n\n"
            f"Your email verification code is: {code}\n\n"
            f"This code will expire in {CODE_TTL_MINUTES} minutes.\n"
            "If you did not request this code, you can ignore this email."
        ),
    )


# =========================================================
# SEND PASSWORD RESET CODE
# =========================================================


def send_password_reset_email(
    recipient_email: str,
    code: str,
    first_name: str = "",
) -> None:
    """Email the 6-digit password reset code. Raises EmailSendError."""

    name = html.escape(first_name.strip())
    greeting = f"Hello {name}," if name else "Hello,"

    _send_email(
        recipient_email=recipient_email,
        recipient_name=first_name.strip(),
        subject="Centrum Laboratory - Password Reset Code",
        html_content=_email_layout(
            greeting=greeting,
            intro="Use this code to reset your password:",
            code=html.escape(code),
            footer=(
                "If you did not ask to reset your password, you can ignore "
                "this email. Your password will not change."
            ),
        ),
        text_content=(
            f"{greeting}\n\n"
            f"Use this code to reset your password: {code}\n\n"
            f"This code will expire in {CODE_TTL_MINUTES} minutes.\n"
            "If you did not ask to reset your password, you can ignore this email."
        ),
    )
