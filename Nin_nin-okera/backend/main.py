import logging
import os
import secrets
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import (
    admin_service,
    inventory_service,
    perf,
    teacher_service,
    technician_service,
)
from .auth_service import forget_cached_tokens
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
# TIMING + CACHE CLEARING (speed)
# =========================================================
#
# * Logs how long every request took (path only - never the query string,
#   tokens or bodies). Requests slower than SLOW_REQUEST_MS are logged as
#   warnings so they stand out. The time is also sent back in the
#   X-Process-Time-Ms header.
#
# * Any request that can change data (POST, PATCH, PUT, DELETE) clears the
#   short-lived read cache (perf.py), so the next read always sees the
#   change. Requests that change ACCOUNTS (see _ACCOUNT_WRITE_PREFIXES) also
#   clear the remembered token checks (auth_service.py), so a deactivated
#   account or a changed role takes effect on the very next request.

SLOW_REQUEST_MS = 1000

_READ_METHODS = ("GET", "HEAD", "OPTIONS")

# Writes that can change who may sign in, or as what (account status, role,
# email, deactivation, password). Only these clear the remembered token
# checks; other changes (reports, inventory, notifications...) don't affect
# them, so users keep their 60-second token check instead of paying two
# extra round trips to Supabase on the next click after any save.
_ACCOUNT_WRITE_PREFIXES = (
    "/users",
    "/admin/requests",
    "/admin/email",
    "/admin/change-password",
    "/technician/change-password",
    "/auth/reset-password",
)


def _changes_accounts(path: str) -> bool:
    return path.startswith(_ACCOUNT_WRITE_PREFIXES) or "deactivate" in path


# POST requests that change NO table the dashboards read: logging in and the
# sign-up / reset code steps (codes are kept in memory, not in the database).
# They used to clear the shared dashboard cache for everyone on every login.
# /auth/create-account is not here: it adds a Users row.
_NO_DATA_CHANGE_PATHS = {
    "/auth/login",
    "/auth/send-code",
    "/auth/resend-code",
    "/auth/verify-code",
    "/auth/signup",
    "/auth/forgot-password",
    "/notifications/read",
}

from . import database


@app.on_event("startup")
def _warm_up():
    for _ in range(8):
        perf.background(database.round_trip_ms)
    perf.background(roles_problem)  # loads the Role table


@app.middleware("http")
async def timing_and_cache(request: Request, call_next):

    start = time.perf_counter()
    is_write = (
        request.method not in _READ_METHODS
        and request.url.path not in _NO_DATA_CHANGE_PATHS
    )

    if is_write:
        perf.invalidate()

    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        if is_write:
            perf.invalidate()
            if _changes_accounts(request.url.path):
                forget_cached_tokens()

        ms = (time.perf_counter() - start) * 1000
        level = logging.WARNING if ms >= SLOW_REQUEST_MS else logging.INFO
        logger.log(
            level,
            "%s %s -> %s in %.0f ms",
            request.method,
            request.url.path,
            status_code,
            ms,
        )

    response.headers["X-Process-Time-Ms"] = f"{ms:.0f}"
    return response


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
# The /users admin endpoints change accounts, so they require either
#   - "Authorization: Bearer <access token>" of a logged-in Admin, or
#   - the X-Admin-Token header matching ADMIN_API_TOKEN from .env.


def _require_admin(token: str | None, authorization: str | None = None):

    bearer = (authorization or "").strip()

    if bearer.lower().startswith("bearer "):

        bearer = bearer[7:].strip()

    if bearer and admin_service.current_admin(bearer).get("success"):

        return

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


class ReportStatusRequest(BaseModel):

    status: str
    note: str = ""


class EscalationRequest(BaseModel):

    room: str
    unit_number: int
    status: str


class ContactNumberRequest(BaseModel):

    contact_number: str


class ChangePasswordRequest(BaseModel):

    current_password: str
    new_password: str


class MarkReadRequest(BaseModel):

    ids: list[int] | None = None  # None = all of my notifications


class ChangeEmailRequest(BaseModel):

    new_email: str
    current_password: str


class RequestDecisionRequest(BaseModel):

    decision: str
    reason: str = ""


class UserUpdateRequest(BaseModel):

    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department: str | None = None
    role: str | None = None
    role_id: int | str | None = None
    contact_number: str | None = None
    status: str | None = None


class EscalationDecisionRequest(BaseModel):

    decision: str  # approve | resolve | back (send_back)


class LaboratoryRequest(BaseModel):

    room: str  # Computers.Room for every unit of the laboratory
    units: int = 0  # UnitNumber 1..units
    hardware: dict | None = None  # specs copied to every unit (ComputerHardware)


class InventoryComputerRequest(BaseModel):

    room: str = ""
    unit_number: int = 0
    brand: str | None = None
    model: str | None = None
    serial: str | None = None
    status: str | None = None
    hardware: dict | None = None
    software: list[dict] = []
    history: list[dict] = []  # [{"kind", "text"}] -> MaintenanceHistory


class InventorySoftwareRequest(BaseModel):

    name: str = ""
    version: str = ""
    history: list[dict] = []


class InventoryMaintenanceRequest(BaseModel):

    kind: str = "Other"
    text: str = ""
    done_by: str = ""


class FollowUpRequest(BaseModel):

    message: str = ""


class SubmitReportRequest(BaseModel):

    computer_id: int
    issues: list[str]
    comment: str = ""
    # "Hardware" or "Software", as picked on the teacher's form (Reports.CategoryId)
    category: str = ""


class CancelReportRequest(BaseModel):
    reason: str = ""


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

    # The email was checked just above (email_taken), so it isn't checked again.
    result = start_email_verification(
        email=data.email, first_name=data.first_name, check_taken=False
    )

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
    authorization: str | None = Header(default=None),
):

    _require_admin(x_admin_token, authorization)

    return admin_list_users(status=status, role=role)


@app.get("/users/{user_id}")
def get_user(
    user_id: str,
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):

    _require_admin(x_admin_token, authorization)

    result = admin_get_user(user_id)

    if not result["success"]:

        _fail(result, status_code=404)

    return result


@app.patch("/users/{user_id}")
def update_user(
    user_id: str,
    data: UserUpdateRequest,
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):

    _require_admin(x_admin_token, authorization)

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
    user_id: str,
    data: StatusRequest,
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):

    _require_admin(x_admin_token, authorization)

    result = admin_set_status(user_id, data.status)

    if not result["success"]:

        _fail(result)

    return result


@app.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):

    _require_admin(x_admin_token, authorization)

    result = admin_delete_user(user_id)

    if not result["success"]:

        _fail(result, status_code=404)

    return result


# =========================================================
# TECHNICIAN  (requires the login's access token)
# =========================================================
# backend_client sends "Authorization: Bearer <access_token from /auth/login>".
# technician_service checks it with auth_service and allows Technicians only.


def _require_technician(authorization: str | None) -> dict:

    token = (authorization or "").strip()

    if token.lower().startswith("bearer "):

        token = token[7:].strip()

    result = technician_service.current_technician(token)

    if not result["success"]:

        _fail(result, status_code=result.get("status_code", 401))

    return result["user"]


@app.get("/technician/dashboard")
def technician_dashboard(authorization: str | None = Header(default=None)):

    _require_technician(authorization)

    return technician_service.get_dashboard_data()


@app.patch("/technician/reports/{report_id}")
def technician_update_report(
    report_id: str,
    data: ReportStatusRequest,
    authorization: str | None = Header(default=None),
):

    technician = _require_technician(authorization)

    result = technician_service.update_report_status(
        report_id, data.status, data.note, technician
    )

    if not result["success"]:

        _fail(result)

    return result


@app.patch("/technician/escalation")
def technician_set_escalation(
    data: EscalationRequest, authorization: str | None = Header(default=None)
):

    _require_technician(authorization)

    result = technician_service.set_escalation_status(
        data.room, data.unit_number, data.status
    )

    if not result["success"]:

        _fail(result)

    return result


@app.patch("/technician/profile")
def technician_update_profile(
    data: ContactNumberRequest, authorization: str | None = Header(default=None)
):

    technician = _require_technician(authorization)

    result = technician_service.update_contact_number(technician, data.contact_number)

    if not result["success"]:

        _fail(result)

    return result


@app.post("/technician/change-password")
def technician_change_password(
    data: ChangePasswordRequest, authorization: str | None = Header(default=None)
):

    technician = _require_technician(authorization)

    result = technician_service.change_password(
        technician, data.current_password, data.new_password
    )

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# ADMIN DASHBOARD  (requires the login's access token)
# =========================================================
# backend_client sends "Authorization: Bearer <access_token from /auth/login>".
# admin_service checks it with auth_service and allows Admins only.
# (The /users endpoints above keep using X-Admin-Token.)


def _require_dashboard_admin(authorization: str | None) -> dict:

    token = (authorization or "").strip()

    if token.lower().startswith("bearer "):

        token = token[7:].strip()

    result = admin_service.current_admin(token)

    if not result["success"]:

        _fail(result, status_code=result.get("status_code", 401))

    return result["user"]


@app.get("/admin/dashboard")
def admin_dashboard(authorization: str | None = Header(default=None)):

    _require_dashboard_admin(authorization)

    return admin_service.get_dashboard_data()


@app.patch("/admin/requests/{user_id}")
def admin_decide_request(
    user_id: str,
    data: RequestDecisionRequest,
    authorization: str | None = Header(default=None),
):

    _require_dashboard_admin(authorization)

    result = admin_service.decide_user_request(user_id, data.decision, data.reason)

    if not result["success"]:

        _fail(result)

    return result


@app.patch("/admin/reports/{report_id}/escalation")
def admin_decide_escalation(
    report_id: str,
    data: EscalationDecisionRequest,
    authorization: str | None = Header(default=None),
):
    """Approve / resolve / send back an escalated report (Admin only)."""

    admin = _require_dashboard_admin(authorization)

    result = admin_service.decide_escalation(admin, report_id, data.decision)

    if not result.get("success"):

        _fail(result)

    return result


@app.post("/admin/laboratories")
def admin_create_laboratory(
    data: LaboratoryRequest,
    authorization: str | None = Header(default=None),
):
    """Add a laboratory: its computer units are saved to public."Computers"
    (Room + UnitNumber 1..units) and returned as stored (Admin only)."""

    admin = _require_dashboard_admin(authorization)

    result = admin_service.create_laboratory(
        admin, data.room, data.units, data.hardware
    )

    if not result.get("success"):

        _fail(result, 409 if result.get("code") == "duplicate" else 400)

    return result


# =========================================================
# INVENTORY (Admin and Technician) -> Supabase
# =========================================================


def _require_inventory_user(authorization: str | None) -> dict:
    """A signed-in Admin or Technician."""

    token = (authorization or "").strip()

    if token.lower().startswith("bearer "):

        token = token[7:].strip()

    result = admin_service.current_admin(token)

    if result.get("success"):

        return result["user"]

    result = technician_service.current_technician(token)

    if result.get("success"):

        return result["user"]

    _fail(
        {"error": "Only Admins and Technicians can change the inventory."},
        status_code=result.get("status_code", 401),
    )


def _dump(data: BaseModel, exclude_unset: bool = False) -> dict:

    if hasattr(data, "model_dump"):

        return data.model_dump(exclude_unset=exclude_unset)

    return data.dict(exclude_unset=exclude_unset)  # pydantic v1


def _inventory_result(result: dict) -> dict:

    if not result.get("success"):

        code = result.get("code")

        _fail(
            result, 409 if code == "duplicate" else 404 if code == "not_found" else 400
        )

    return result


@app.post("/inventory/computers")
def inventory_add_computer(
    data: InventoryComputerRequest, authorization: str | None = Header(default=None)
):
    user = _require_inventory_user(authorization)

    return _inventory_result(inventory_service.create_computer(user, _dump(data)))


@app.patch("/inventory/computers/{computer_id}")
def inventory_update_computer(
    computer_id: int,
    data: InventoryComputerRequest,
    authorization: str | None = Header(default=None),
):
    user = _require_inventory_user(authorization)

    return _inventory_result(
        inventory_service.update_computer(
            user, computer_id, _dump(data, exclude_unset=True)
        )
    )


@app.post("/inventory/computers/{computer_id}/software")
def inventory_install_software(
    computer_id: int,
    data: InventorySoftwareRequest,
    authorization: str | None = Header(default=None),
):
    user = _require_inventory_user(authorization)

    return _inventory_result(
        inventory_service.install_software(
            user, computer_id, data.name, data.version, data.history
        )
    )


@app.patch("/inventory/software/{software_id}")
def inventory_update_software(
    software_id: int,
    data: InventorySoftwareRequest,
    authorization: str | None = Header(default=None),
):
    user = _require_inventory_user(authorization)

    return _inventory_result(
        inventory_service.update_software(user, software_id, data.version, data.history)
    )


@app.post("/inventory/software/{software_id}/remove")
def inventory_remove_software(
    software_id: int,
    data: InventorySoftwareRequest,
    authorization: str | None = Header(default=None),
):
    user = _require_inventory_user(authorization)

    return _inventory_result(
        inventory_service.remove_software(user, software_id, data.history)
    )


@app.post("/inventory/computers/{computer_id}/maintenance")
def inventory_log_maintenance(
    computer_id: int,
    data: InventoryMaintenanceRequest,
    authorization: str | None = Header(default=None),
):
    user = _require_inventory_user(authorization)

    return _inventory_result(
        inventory_service.log_maintenance(
            user, computer_id, data.kind, data.text, data.done_by
        )
    )


@app.patch("/admin/profile")
def admin_update_profile(
    data: ContactNumberRequest, authorization: str | None = Header(default=None)
):

    admin = _require_dashboard_admin(authorization)

    result = admin_service.update_contact_number(admin, data.contact_number)

    if not result["success"]:

        _fail(result)

    return result


@app.post("/admin/change-password")
def admin_change_password(
    data: ChangePasswordRequest, authorization: str | None = Header(default=None)
):

    admin = _require_dashboard_admin(authorization)

    result = admin_service.change_password(
        admin, data.current_password, data.new_password
    )

    if not result["success"]:

        _fail(result)

    return result


@app.post("/admin/email")
def admin_change_email(
    data: ChangeEmailRequest, authorization: str | None = Header(default=None)
):

    admin = _require_dashboard_admin(authorization)

    result = admin_service.change_email(admin, data.new_email, data.current_password)

    if not result["success"]:

        _fail(result)

    return result


# =========================================================
# NOTIFICATIONS  (any logged-in user; only their own)
# =========================================================


def _require_user(authorization: str | None) -> dict:

    token = (authorization or "").strip()

    if token.lower().startswith("bearer "):

        token = token[7:].strip()

    from .auth_service import user_from_token

    result = user_from_token(token)

    if not result.get("success"):

        _fail(result, status_code=401)

    return result["user"]


@app.get("/notifications")
def my_notifications(limit: int = 50, authorization: str | None = Header(default=None)):

    from . import notification_service

    user = _require_user(authorization)

    return {
        "success": True,
        "notifications": notification_service.list_for_user(user.get("user_id"), limit),
    }


@app.patch("/notifications/read")
def read_my_notifications(
    data: MarkReadRequest, authorization: str | None = Header(default=None)
):

    from . import notification_service

    user = _require_user(authorization)

    n = notification_service.mark_read(user.get("user_id"), data.ids)

    return {"success": True, "updated": n}


# =========================================================
# TEACHER  (requires the login's access token)
# =========================================================
# backend_client sends "Authorization: Bearer <access_token from /auth/login>".
# teacher_service checks it with auth_service and allows Teachers only.


def _require_teacher(authorization: str | None) -> dict:

    token = (authorization or "").strip()

    if token.lower().startswith("bearer "):

        token = token[7:].strip()

    # Checked here with auth_service, so it works with any version of
    # teacher_service.py (some have no current_teacher()).
    from .auth_service import user_from_token

    result = user_from_token(token)

    if not result.get("success"):

        _fail(result, status_code=401)

    user = result.get("user") or {}

    if str(user.get("role") or "").strip().lower() != "teacher":

        _fail({"error": "This page is for teachers only."}, status_code=403)

    return user


@app.get("/teacher/dashboard")
def teacher_dashboard(authorization: str | None = Header(default=None)):
    """
    Returns computers (with hardware and software) and the
    authenticated teacher's own reports in one call.
    """

    teacher = _require_teacher(authorization)

    try:
        return teacher_service.get_dashboard_data(teacher)
    except Exception as exc:
        logger.exception("teacher_dashboard failed")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@app.get("/teacher/computers")
def teacher_computers(authorization: str | None = Header(default=None)):
    """All computers with hardware and software — used to populate the floor map."""

    _require_teacher(authorization)

    try:
        return {"success": True, "computers": teacher_service.get_computers()}
    except Exception as exc:
        logger.exception("teacher_computers failed")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@app.get("/teacher/reports")
def teacher_reports(authorization: str | None = Header(default=None)):
    """The authenticated teacher's own reports only."""

    teacher = _require_teacher(authorization)

    try:
        return {
            "success": True,
            "reports": teacher_service.get_reports(teacher),
        }
    except Exception as exc:
        logger.exception("teacher_reports failed")
        raise HTTPException(status_code=500, detail=str(exc)) from None


@app.post("/teacher/reports")
def teacher_submit_report(
    data: SubmitReportRequest,
    authorization: str | None = Header(default=None),
):
    """Submit a new issue report for a computer."""

    teacher = _require_teacher(authorization)

    try:
        inserted = teacher_service.submit_report(
            teacher,
            computer_id=data.computer_id,
            issues=data.issues,
            comment=data.comment,
            category=data.category,
        )
        return {"success": True, "report": inserted}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@app.post("/teacher/reports/{report_id}/follow-up")
def teacher_follow_up_report(
    report_id: str,
    data: FollowUpRequest,
    authorization: str | None = Header(default=None),
):
    """Follow up one of the teacher's own reports that no technician has
    picked up yet (after 2 days, at most once a day). Notifies the technicians."""

    teacher = _require_teacher(authorization)

    try:
        updated = teacher_service.follow_up_report(teacher, report_id, data.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    return {
        "success": True,
        "message": "Follow-up sent to the technicians.",
        "report": updated,
    }


@app.post("/teacher/reports/{report_id}/cancel")
def teacher_cancel_report(
    report_id: str,
    data: CancelReportRequest,
    authorization: str | None = Header(default=None),
):
    teacher = _require_teacher(authorization)
    try:
        updated = teacher_service.cancel_report(teacher, report_id, data.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    return {"success": True, "message": "Report cancelled.", "report": updated}


@app.get("/teacher/profile")
def teacher_profile(authorization: str | None = Header(default=None)):
    """Return the authenticated teacher's Users row."""

    teacher = _require_teacher(authorization)

    profile = teacher_service.get_profile(teacher)

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    return {"success": True, "profile": profile}


@app.patch("/teacher/profile")
def teacher_update_profile(
    data: ContactNumberRequest,
    authorization: str | None = Header(default=None),
):
    """Update the teacher's contact number in Users."""

    teacher = _require_teacher(authorization)

    try:
        updated = teacher_service.update_contact_number(teacher, data.contact_number)
        return {
            "success": True,
            "message": "Contact number updated.",
            "user": updated,
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/teacher/report-issues")
def teacher_report_issues(authorization: str | None = Header(default=None)):
    """Available issue options from the ReportIssues table."""

    _require_teacher(authorization)

    return {"success": True, "issues": teacher_service.get_report_issues()}


@app.get("/teacher/report-statuses")
def teacher_report_statuses(authorization: str | None = Header(default=None)):
    """All rows from the ReportStatus table."""

    _require_teacher(authorization)

    return {"success": True, "statuses": teacher_service.get_report_statuses()}
