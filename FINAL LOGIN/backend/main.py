import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth_service import (
    admin_delete_user,
    admin_get_user,
    admin_list_users,
    admin_set_status,
    admin_update_user,
    authenticate,
    complete_password_reset,
    create_account,
    database_problem,
    email_taken,
    resend_verification_code,
    roles_problem,
    save_pending_signup,
    start_email_verification,
    start_password_reset,
    validate_password,
    verify_verification_code,
)
from .database import config_problems as database_config_problems
from .email_service import email_config_problems
from .users_repository import DatabaseError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("centrum.api")


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(title="Centrum Laboratory API", version="1.1.0")


# =========================================================
# ERROR HANDLING
# =========================================================


@app.exception_handler(DatabaseError)
async def database_error(request: Request, error: DatabaseError):
    """Database failures: short message for the user, details already logged."""

    status_code = 400 if error.code == "duplicate" else 503

    return JSONResponse(status_code=status_code, content={"detail": str(error)})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, error: Exception):
    """Log the full error on the server; send the client a short message only."""

    logger.exception("Unhandled error on %s %s", request.method, request.url.path)

    return JSONResponse(
        status_code=500,
        content={
            "detail": ("Something went wrong on the server. " "Please try again.")
        },
    )


def _fail(result: dict, status_code: int = 400):

    raise HTTPException(
        status_code=status_code, detail=result.get("error") or "Request failed."
    )


# =========================================================
# ADMIN TOKEN
# =========================================================
# The /users admin endpoints change accounts, so they require the
# X-Admin-Token header to match ADMIN_API_TOKEN from .env.


def _require_admin(token: str | None):

    expected = (os.getenv("ADMIN_API_TOKEN") or "").strip()

    if not expected:

        raise HTTPException(
            status_code=503,
            detail="User management is disabled (ADMIN_API_TOKEN is not set).",
        )

    if not token or not secrets.compare_digest(token.strip(), expected):

        raise HTTPException(
            status_code=403, detail="You are not allowed to manage users."
        )


# =========================================================
# REQUEST MODELS
# =========================================================


class LoginRequest(BaseModel):

    email: str
    password: str


class SendCodeRequest(BaseModel):

    email: str
    first_name: str = ""


class VerifyCodeRequest(BaseModel):

    email: str
    code: str


class SignupRequest(BaseModel):

    email: str
    first_name: str
    last_name: str
    department: str
    role: str
    password: str
    contact_number: str = ""


class EmailRequest(BaseModel):

    email: str
    first_name: str = ""


class ResetPasswordRequest(BaseModel):

    email: str
    code: str
    new_password: str


class StatusRequest(BaseModel):

    status: str


class UserUpdateRequest(BaseModel):

    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department: str | None = None
    role: str | None = None
    role_id: int | str | None = None
    contact_number: str | None = None
    status: str | None = None


# =========================================================
# ROOT
# =========================================================


@app.get("/")
def root():

    return {"message": "Centrum Laboratory API is running"}


# =========================================================
# HEALTH CHECK
# =========================================================


@app.get("/health")
def health():

    # Says WHICH setting is wrong - never shows any value.
    email_problems = email_config_problems()

    db_config = database_config_problems()

    db_problem = " ".join(db_config) if db_config else database_problem()

    return {
        "success": True,
        "message": "Backend is healthy.",
        "email_configured": not email_problems,
        "email_problems": email_problems,
        "database_ok": db_problem is None,
        "database_problem": db_problem,
        "roles_problem": None if db_problem else roles_problem(),
    }


# =========================================================
# CHECK EMAIL
# =========================================================


@app.get("/auth/email-exists")
def check_email_exists(email: str):

    return {"exists": email_taken(email)}


# =========================================================
# SEND VERIFICATION CODE
# =========================================================


@app.post("/auth/send-code")
def send_code(data: SendCodeRequest):

    result = start_email_verification(email=data.email, first_name=data.first_name)

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# RESEND VERIFICATION CODE
# =========================================================


@app.post("/auth/resend-code")
def resend_code(data: EmailRequest):

    result = resend_verification_code(email=data.email)

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# SAVE SIGNUP INFORMATION
# =========================================================


@app.post("/auth/signup")
def signup(data: SignupRequest):

    # -----------------------------------------------
    # Basic validation
    # -----------------------------------------------

    if not data.email.strip():

        raise HTTPException(status_code=400, detail="Email is required.")

    if not data.first_name.strip():

        raise HTTPException(status_code=400, detail="First name is required.")

    if not data.last_name.strip():

        raise HTTPException(status_code=400, detail="Last name is required.")

    if not data.department:

        raise HTTPException(status_code=400, detail="Department is required.")

    if data.role not in ("Teacher", "Technician"):

        raise HTTPException(status_code=400, detail="Invalid role.")

    # -----------------------------------------------
    # Validate password
    # -----------------------------------------------

    valid, error = validate_password(data.password)

    if not valid:

        raise HTTPException(status_code=400, detail=error)

    # -----------------------------------------------
    # Check for a duplicate email in Users
    # -----------------------------------------------

    if email_taken(data.email):

        raise HTTPException(
            status_code=400, detail=("An account with this email " "already exists.")
        )

    # -----------------------------------------------
    # Save signup information
    # -----------------------------------------------

    save_pending_signup(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        department=data.department,
        role=data.role,
        password=data.password,
        contact_number=data.contact_number,
    )

    # -----------------------------------------------
    # Send verification code
    # -----------------------------------------------

    result = start_email_verification(email=data.email, first_name=data.first_name)

    if not result["success"]:

        _fail(result)

    return {"success": True, "message": ("Verification code sent " "to your email.")}


# =========================================================
# VERIFY CODE
# =========================================================


@app.post("/auth/verify-code")
def verify_code(data: VerifyCodeRequest):

    result = verify_verification_code(email=data.email, entered_code=data.code)

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# CREATE ACCOUNT AFTER VERIFICATION
# =========================================================


@app.post("/auth/create-account")
def create_verified_account(data: EmailRequest):

    result = create_account(email=data.email)

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# LOGIN
# =========================================================


@app.post("/auth/login")
def login(data: LoginRequest):

    result = authenticate(email=data.email, password=data.password)

    if not result["success"]:

        _fail(result, status_code=401)

    return result


# =========================================================
# FORGOT PASSWORD - SEND RESET CODE
# =========================================================


@app.post("/auth/forgot-password")
def forgot_password(data: EmailRequest):

    result = start_password_reset(email=data.email)

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# FORGOT PASSWORD - SET NEW PASSWORD
# =========================================================


@app.post("/auth/reset-password")
def reset_password(data: ResetPasswordRequest):

    result = complete_password_reset(
        email=data.email, code=data.code, new_password=data.new_password
    )

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# ADMIN - USERS CRUD  (requires X-Admin-Token)
# =========================================================
# Create = the registration flow above (it also creates the login).


@app.get("/users")
def list_users(
    status: str | None = None,
    role: str | None = None,
    x_admin_token: str | None = Header(default=None),
):

    _require_admin(x_admin_token)

    return admin_list_users(status=status, role=role)


@app.get("/users/{user_id}")
def get_user(user_id: str, x_admin_token: str | None = Header(default=None)):

    _require_admin(x_admin_token)

    result = admin_get_user(user_id)

    if not result["success"]:

        _fail(result, status_code=404)

    return result


@app.patch("/users/{user_id}")
def update_user(
    user_id: str,
    data: UserUpdateRequest,
    x_admin_token: str | None = Header(default=None),
):

    _require_admin(x_admin_token)

    changes = (
        data.model_dump(exclude_none=True)
        if hasattr(data, "model_dump")
        else data.dict(exclude_none=True)
    )

    result = admin_update_user(user_id, changes)

    if not result["success"]:

        _fail(result)

    return result


@app.patch("/users/{user_id}/status")
def set_user_status(
    user_id: str, data: StatusRequest, x_admin_token: str | None = Header(default=None)
):

    _require_admin(x_admin_token)

    result = admin_set_status(user_id, data.status)

    if not result["success"]:

        _fail(result)

    return result


@app.delete("/users/{user_id}")
def delete_user(user_id: str, x_admin_token: str | None = Header(default=None)):

    _require_admin(x_admin_token)

    result = admin_delete_user(user_id)

    if not result["success"]:

        _fail(result, status_code=404)

    return result
