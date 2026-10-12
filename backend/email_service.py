"""
Centrum Laboratory - Email Service
===================================

Centralized outgoing email service using Brevo Transactional Email API.

This module is responsible ONLY for sending application emails.
It does not access the database directly.

Authentication/user information is handled by:
    - auth_service.py
    - users_repository.py

This service is used by auth_service.py for:
    - Email verification during account registration
    - Password reset verification

Required .env values:

    BREVO_API_KEY=your_brevo_api_key
    BREVO_SENDER_EMAIL=your_verified_email@example.com
    BREVO_SENDER_NAME=Computer Laboratory Monitoring System

BREVO_SENDER_EMAIL must be a sender verified in Brevo.

Never hardcode real API keys or credentials in this file.
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


# ============================================================
# ENVIRONMENT LOADING
# ============================================================

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# The project uses:
#
# CL Monitoring System/
# ├── .env
# ├── backend/
# │   └── email_service.py
# └── frontend/
#
# Check the project root first, then backend, then the current
# working directory.
for candidate in (
    PROJECT_ROOT / ".env",
    HERE / ".env",
):
    if candidate.is_file():
        load_dotenv(candidate)

load_dotenv(find_dotenv(usecwd=True))


# ============================================================
# SETTINGS
# ============================================================

DEFAULT_SENDER_NAME = "Computer Laboratory Monitoring System"

# Must match CODE_TTL in auth_service.py.
CODE_TTL_MINUTES = 10

# Authentication codes used by auth_service.py are six digits.
CODE_LENGTH = 6


# Valid email format for application-level validation.
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Valid verification/reset code.
CODE_REGEX = re.compile(rf"^\d{{{CODE_LENGTH}}}$")


# Example values that should never be treated as real
# Brevo sender addresses.
PLACEHOLDER_SENDERS = {
    "your_verified_email@example.com",
    "your_verified_sender_email",
    "you@example.com",
}


# ============================================================
# ERRORS
# ============================================================


class EmailConfigError(RuntimeError):
    """Brevo email configuration is missing or invalid."""


class EmailSendError(RuntimeError):
    """
    Brevo refused the email or the email service could not
    be reached.

    The message is intentionally safe to display to users.
    Sensitive Brevo/API details are logged only on the server.
    """


# ============================================================
# ENVIRONMENT HELPERS
# ============================================================


def _clean(value: str | None) -> str:
    """
    Clean an environment variable value.

    Removes surrounding whitespace and one pair of matching
    single/double quotes.
    """
    value = (value or "").strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()

    return value


# ============================================================
# EMAIL VALIDATION
# ============================================================


def _is_valid_email(email: str) -> bool:
    """Return True when the supplied value has a basic valid email format."""
    return bool(EMAIL_REGEX.fullmatch(email.strip()))


def _is_valid_code(code: str) -> bool:
    """Return True when the supplied authentication code is six digits."""
    return bool(CODE_REGEX.fullmatch(code.strip()))


# ============================================================
# BREVO CONFIGURATION
# ============================================================


def email_config_problems() -> list[str]:
    """
    Return configuration problems without exposing secret values.
    """

    problems: list[str] = []

    api_key = _clean(os.getenv("BREVO_API_KEY"))
    sender_email = _clean(os.getenv("BREVO_SENDER_EMAIL"))

    if not api_key:
        problems.append("BREVO_API_KEY is missing from .env.")

    if not sender_email:
        problems.append("BREVO_SENDER_EMAIL is missing from .env.")
    elif sender_email.lower() in {value.lower() for value in PLACEHOLDER_SENDERS}:
        problems.append("BREVO_SENDER_EMAIL still contains a placeholder value.")
    elif not _is_valid_email(sender_email):
        problems.append("BREVO_SENDER_EMAIL is not a valid email address.")

    return problems


def get_email_config() -> dict[str, str]:
    """
    Return the cleaned Brevo configuration.

    Raises:
        EmailConfigError: If required configuration is missing
        or invalid.
    """

    problems = email_config_problems()

    if problems:
        raise EmailConfigError(" ".join(problems))

    return {
        "api_key": _clean(os.getenv("BREVO_API_KEY")),
        "sender_email": _clean(os.getenv("BREVO_SENDER_EMAIL")),
        "sender_name": (_clean(os.getenv("BREVO_SENDER_NAME")) or DEFAULT_SENDER_NAME),
    }


# ============================================================
# STARTUP CONFIGURATION CHECK
# ============================================================

for problem in email_config_problems():
    logger.warning("Email configuration: %s", problem)


# ============================================================
# BREVO CLIENT
# ============================================================

_api_cache: dict[str, sib_api_v3_sdk.TransactionalEmailsApi] = {}


def _get_api(
    api_key: str,
) -> sib_api_v3_sdk.TransactionalEmailsApi:
    """
    Return a cached Brevo TransactionalEmailsApi client.

    A new client is created only when the API key is not already
    cached.
    """

    api = _api_cache.get(api_key)

    if api is not None:
        return api

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = api_key

    api_client = sib_api_v3_sdk.ApiClient(configuration)

    api = sib_api_v3_sdk.TransactionalEmailsApi(api_client)

    # Keep only the currently active API client.
    _api_cache.clear()
    _api_cache[api_key] = api

    return api


# ============================================================
# BREVO ERROR HANDLING
# ============================================================


def _brevo_error_details(
    error: ApiException,
) -> tuple[str, str]:
    """
    Extract Brevo's error code and message from the response body.

    Never returns API credentials or request headers.
    """

    try:
        body = json.loads(error.body or "{}")

        return (
            str(body.get("code", "")),
            str(body.get("message", "")),
        )

    except (TypeError, ValueError):
        return "", ""


def _friendly_message(
    status: int | None,
    code: str,
    message: str,
) -> str:
    """
    Convert a Brevo error into a safe user-facing message.
    """

    text = f"{code} {message}".lower()

    if status == 401 or "key not found" in text or "unauthorized" in text:
        return (
            "The email service is not configured correctly. "
            "Please contact the administrator."
        )

    if "sender" in text or "from" in text and "email" in text:
        return (
            "The email sender is not set up or verified. "
            "Please contact the administrator."
        )

    if status == 429:
        return "Too many emails were sent. " "Please wait a moment and try again."

    if status is not None and 400 <= status < 500:
        return "The email request could not be processed. " "Please try again later."

    return "We couldn't send the email right now. " "Please try again later."


# ============================================================
# EMAIL CONTENT VALIDATION
# ============================================================


def _validate_recipient(recipient_email: str) -> str:
    """
    Validate and normalize a recipient email address.
    """

    email = (recipient_email or "").strip()

    if not email:
        raise EmailSendError("A recipient email address is required.")

    if not _is_valid_email(email):
        raise EmailSendError("The recipient email address is invalid.")

    return email


def _validate_code(code: str) -> str:
    """
    Validate and normalize a verification/reset code.
    """

    normalized_code = (code or "").strip()

    if not _is_valid_code(normalized_code):
        raise EmailSendError("The verification code is invalid.")

    return normalized_code


# ============================================================
# SEND EMAIL
# ============================================================


def _send_email(
    recipient_email: str,
    subject: str,
    html_content: str,
    text_content: str,
    recipient_name: str = "",
) -> None:
    """
    Send one transactional email through Brevo.

    This is the only function in this module that actually
    communicates with Brevo.
    """

    recipient_email = _validate_recipient(recipient_email)

    try:
        config = get_email_config()

    except EmailConfigError as error:
        logger.error(
            "Email not sent - configuration error: %s",
            error,
        )

        raise EmailSendError(
            "The email service is not configured. " "Please contact the administrator."
        ) from None

    sender = sib_api_v3_sdk.SendSmtpEmailSender(
        email=config["sender_email"],
        name=config["sender_name"],
    )

    recipient = sib_api_v3_sdk.SendSmtpEmailTo(
        email=recipient_email,
        name=recipient_name.strip() or None,
    )

    message = sib_api_v3_sdk.SendSmtpEmail(
        sender=sender,
        to=[recipient],
        subject=subject,
        html_content=html_content,
        text_content=text_content,
    )

    try:
        api = _get_api(config["api_key"])
        api.send_transac_email(message)

        logger.info(
            "Email '%s' sent to %s",
            subject,
            recipient_email,
        )

    except ApiException as error:
        code, brevo_message = _brevo_error_details(error)

        # Never log:
        # - API key
        # - authorization headers
        # - request body containing credentials
        logger.error(
            "Brevo rejected email " "(status=%s, code=%s): %s",
            error.status,
            code or "-",
            brevo_message or "-",
        )

        raise EmailSendError(
            _friendly_message(
                error.status,
                code,
                brevo_message,
            )
        ) from None

    except Exception as error:
        logger.error(
            "Could not reach Brevo: %s",
            type(error).__name__,
        )

        raise EmailSendError(
            "We couldn't reach the email service. " "Please try again later."
        ) from None


# ============================================================
# EMAIL TEMPLATE
# ============================================================


def _email_layout(
    greeting: str,
    intro: str,
    code: str,
    footer: str,
) -> str:
    """
    Build the common HTML email layout used by authentication
    emails.
    """

    sender_name = html.escape(
        _clean(os.getenv("BREVO_SENDER_NAME")) or DEFAULT_SENDER_NAME
    )

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">
    <title>{sender_name}</title>
</head>

<body style="
    margin: 0;
    padding: 20px;
    background-color: #f9fafb;
    font-family: Arial, sans-serif;
    color: #111827;
">

    <div style="
        max-width: 600px;
        margin: 0 auto;
        background-color: #ffffff;
        padding: 30px;
        border-radius: 8px;
    ">

        <h2>{sender_name}</h2>

        <p>{greeting}</p>

        <p>{intro}</p>

        <div style="
            margin: 25px 0;
            text-align: center;
        ">
            <span style="
                display: inline-block;
                padding: 15px 25px;
                background-color: #f3f4f6;
                border-radius: 6px;
                font-size: 28px;
                font-weight: bold;
                letter-spacing: 8px;
            ">
                {code}
            </span>
        </div>

        <p>
            This code will expire in
            <strong>{CODE_TTL_MINUTES} minutes</strong>.
        </p>

        <p>{footer}</p>

        <p>
            &mdash; {sender_name}
        </p>

    </div>

</body>
</html>
"""


# ============================================================
# VERIFICATION EMAIL
# ============================================================


def send_verification_email(
    recipient_email: str,
    code: str,
    first_name: str = "",
) -> None:
    """
    Send the six-digit email verification code used during
    account registration.

    Called by auth_service.py.
    """

    recipient_email = _validate_recipient(recipient_email)
    code = _validate_code(code)

    first_name = (first_name or "").strip()
    safe_first_name = html.escape(first_name)

    greeting = f"Hello {safe_first_name}," if safe_first_name else "Hello,"

    _send_email(
        recipient_email=recipient_email,
        recipient_name=first_name,
        subject=("Computer Laboratory Monitoring System " "- Email Verification Code"),
        html_content=_email_layout(
            greeting=greeting,
            intro="Your email verification code is:",
            code=html.escape(code),
            footer=(
                "If you did not request this code, " "you can safely ignore this email."
            ),
        ),
        text_content=(
            f"{greeting}\n\n"
            f"Your email verification code is: {code}\n\n"
            f"This code will expire in "
            f"{CODE_TTL_MINUTES} minutes.\n\n"
            "If you did not request this code, "
            "you can safely ignore this email."
        ),
    )


# ============================================================
# PASSWORD RESET EMAIL
# ============================================================


def send_password_reset_email(
    recipient_email: str,
    code: str,
    first_name: str = "",
) -> None:
    """
    Send the six-digit password reset code.

    Called by auth_service.py.
    """

    recipient_email = _validate_recipient(recipient_email)
    code = _validate_code(code)

    first_name = (first_name or "").strip()
    safe_first_name = html.escape(first_name)

    greeting = f"Hello {safe_first_name}," if safe_first_name else "Hello,"

    _send_email(
        recipient_email=recipient_email,
        recipient_name=first_name,
        subject=("Computer Laboratory Monitoring System " "- Password Reset Code"),
        html_content=_email_layout(
            greeting=greeting,
            intro="Use this code to reset your password:",
            code=html.escape(code),
            footer=(
                "If you did not request a password reset, "
                "you can safely ignore this email. "
                "Your password will not be changed."
            ),
        ),
        text_content=(
            f"{greeting}\n\n"
            f"Use this code to reset your password: {code}\n\n"
            f"This code will expire in "
            f"{CODE_TTL_MINUTES} minutes.\n\n"
            "If you did not request a password reset, "
            "you can safely ignore this email. "
            "Your password will not be changed."
        ),
    )
