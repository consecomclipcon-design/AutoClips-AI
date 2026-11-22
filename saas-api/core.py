"""Infrastructure and exact-once credit ledger. Never import secrets into browser code."""
from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx
import psycopg
from cryptography.fernet import Fernet
from fastapi import Depends, Header, HTTPException
from psycopg.rows import dict_row

SCHEMA = "autoclips_saas"
CREDIT_PRICE_CENTS = 15
MAX_CREDITS_PER_CHECKOUT = 100_000
YOUTUBE_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_SCOPES = [YOUTUBE_READ_SCOPE, YOUTUBE_UPLOAD_SCOPE]


def config(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {key} is required")
    return value


def encrypt_token(value: str) -> str:
    return Fernet(config("TOKEN_FERNET_KEY").encode()).encrypt(value.encode()).decode()


def decrypt_token(value: str) -> str:
    return Fernet(config("TOKEN_FERNET_KEY").encode()).decrypt(value.encode()).decode()


def digest_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def iso_now() -> datetime:
    return datetime.now(timezone.utc)


def database():
    """Trusted database connection; every tenant route must verify membership."""
    return psycopg.connect(config("DATABASE_URL"), row_factory=dict_row, autocommit=True)


def db_dep():
    with database() as connection:
        yield connection


def current_user(authorization: str | None = Header(default=None)) -> UUID:
    """Verify the actual Supabase access token with Supabase Auth, not JWT payload claims."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    if len(token) > 8192 or not token:
        raise HTTPException(401, "Invalid session")
    try:
        res = httpx.get(
            config("SUPABASE_URL").rstrip("/") + "/auth/v1/user",
            headers={"apikey": config("SUPABASE_PUBLISHABLE_KEY"), "Authorization": "Bearer " + token},
            timeout=10.0,
        )
        res.raise_for_status()
        return UUID(res.json()["id"])
    except Exception:
        raise HTTPException(401, "Expired or invalid session")


def require_member(conn, org_id: UUID, user_id: UUID, roles=None) -> dict:
    row = conn.execute(
        "select role from autoclips_saas.memberships where org_id=%s and user_id=%s",
        (org_id, user_id),
    ).fetchone()
    if not row or (roles is not None and row["role"] not in roles):
        # Return same response for missing org and user-without-access (no enumeration).
        raise HTTPException(404, "Workspace not found")
    return row


def reserve_credit(conn, org_id: UUID, job_id: UUID, approved_by: UUID) -> dict:
    """Must run inside conn.transaction(); locks wallet and job in that order.

    Distinct approved jobs can never spend the same credit.
    Idempotent for repeated approval of one existing job.
    """
    wallet = conn.execute(
        "select available,reserved from autoclips_saas.wallets where org_id=%s for update",
        (org_id,),
    ).fetchone()
    if wallet is None:
        raise HTTPException(404, "Wallet not found")
    job = conn.execute(
        "select * from autoclips_saas.jobs where id=%s and org_id=%s for update",
        (job_id, org_id),
    ).fetchone()
    if job is None:
        raise HTTPException(404, "Job not found")
    if job["credit_state"] == "reserved" and job["status"] in ("queued", "uploading"):
        return job
    if job["status"] != "ready" or job["credit_state"] != "none":
        raise HTTPException(409, "Job cannot be approved in this state")
    if not wallet["available"]:
        raise HTTPException(402, "No publication credits remaining")
    conn.execute(
        "update autoclips_saas.wallets set available=available-1, reserved=reserved+1, updated_at=now() where org_id=%s",
        (org_id,),
    )
    conn.execute(
        """update autoclips_saas.jobs set credit_state='reserved', status='queued',
           rights_confirmed=true, approved_by=%s, updated_at=now() where id=%s""",
        (approved_by, job_id),
    )
    conn.execute(
        "insert into autoclips_saas.credit_events(org_id,job_id,kind,amount) values(%s,%s,'reserve',-1)",
        (org_id, job_id),
    )
    return conn.execute("select * from autoclips_saas.jobs where id=%s", (job_id,)).fetchone()


def capture_credit(conn, org_id: UUID, job_id: UUID, youtube_video_id: str) -> dict:
    """Only invoke after confirmed YouTube video ID/channel ownership. Transactional."""
    wallet = conn.execute(
        "select available,reserved from autoclips_saas.wallets where org_id=%s for update", (org_id,)
    ).fetchone()
    job = conn.execute(
        "select * from autoclips_saas.jobs where id=%s and org_id=%s for update", (job_id, org_id)
    ).fetchone()
    if wallet is None or job is None:
        raise HTTPException(404, "Job or wallet missing")
    if job["credit_state"] == "captured" and job["youtube_video_id"] == youtube_video_id:
        return job
    if job["credit_state"] != "reserved" or job["status"] not in ("uploading", "needs_reconciliation"):
        raise HTTPException(409, "Job cannot be captured")
    if wallet["reserved"] < 1:
        raise HTTPException(409, "Credit reservation is inconsistent")
    conn.execute(
        "update autoclips_saas.wallets set reserved=reserved-1,updated_at=now() where org_id=%s",
        (org_id,),
    )
    conn.execute(
        """update autoclips_saas.jobs set credit_state='captured',status='published',
           youtube_video_id=%s,last_error=null,updated_at=now() where id=%s""",
        (youtube_video_id, job_id),
    )
    conn.execute(
        "insert into autoclips_saas.credit_events(org_id,job_id,kind,amount) values(%s,%s,'capture',0)",
        (org_id, job_id),
    )
    return conn.execute("select * from autoclips_saas.jobs where id=%s", (job_id,)).fetchone()


def release_credit(conn, org_id: UUID, job_id: UUID) -> dict:
    """Only when uploading has definitely NOT reached YouTube (e.g., queued cancellation)."""
    wallet = conn.execute(
        "select reserved from autoclips_saas.wallets where org_id=%s for update", (org_id,)
    ).fetchone()
    job = conn.execute(
        "select * from autoclips_saas.jobs where id=%s and org_id=%s for update", (job_id, org_id)
    ).fetchone()
    if wallet is None or job is None:
        raise HTTPException(404, "Job or wallet missing")
    if job["credit_state"] == "released":
        return job
    if job["status"] != "queued" or job["credit_state"] != "reserved":
        raise HTTPException(409, "Cannot refund an upload already started")
    conn.execute(
        "update autoclips_saas.wallets set reserved=reserved-1, available=available+1,updated_at=now() where org_id=%s",
        (org_id,),
    )
    conn.execute(
        "update autoclips_saas.jobs set credit_state='released',status='cancelled',updated_at=now() where id=%s",
        (job_id,),
    )
    conn.execute(
        "insert into autoclips_saas.credit_events(org_id,job_id,kind,amount) values(%s,%s,'release',1)",
        (org_id, job_id),
    )
    return conn.execute("select * from autoclips_saas.jobs where id=%s", (job_id,)).fetchone()


def grant_paid_credits(conn, session_id: str, amount_total: int, currency: str) -> bool:
    """Stripe verified signature required at callsite. Same session fulfilled exactly once."""
    checkout = conn.execute(
        "select * from autoclips_saas.stripe_checkouts where session_id=%s for update",
        (session_id,),
    ).fetchone()
    if checkout is None:
        raise HTTPException(400, "Unknown checkout session")
    if checkout["paid_at"] is not None:
        return False
    if currency.lower() != "brl" or amount_total != checkout["amount_cents"]:
        raise HTTPException(400, "Payment amount mismatch")
    org_id, credits = checkout["org_id"], checkout["credits"]
    conn.execute(
        """update autoclips_saas.wallets set available=available+%s,total_purchased=total_purchased+%s,
           updated_at=now() where org_id=%s""",
        (credits, credits, org_id),
    )
    conn.execute(
        """insert into autoclips_saas.credit_events(org_id,kind,amount,external_key)
           values(%s,'purchase',%s,%s)""",
        (org_id, credits, "stripe:" + session_id),
    )
    conn.execute(
        "update autoclips_saas.stripe_checkouts set paid_at=now() where session_id=%s",
        (session_id,),
    )
    return True
