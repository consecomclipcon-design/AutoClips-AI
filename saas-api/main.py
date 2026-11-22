"""AutoClips metadata-only API.

No binary video/media upload endpoints, private media buckets, browser media proxy,
or persistent Google refresh tokens. Clients upload directly to YouTube via GIS.
Server verifies YouTube metadata with a short-lived bearer token passed per request,
without storing it, then captures one credit atomically.
"""
from __future__ import annotations

import os
from uuid import UUID

import httpx
import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core import (
    CREDIT_PRICE_CENTS, capture_credit, config, current_user, database, db_dep,
    grant_paid_credits, release_credit, require_member, reserve_credit,
)

app = FastAPI(
    title="AutoClips SaaS - ZERO MEDIA",
    docs_url="/docs" if os.getenv("ENABLE_API_DOCS") == "1" else None,
    redoc_url=None,
)
origins = [url.strip() for url in os.getenv("APP_ORIGINS", "").split(",") if url.strip()]
app.add_middleware(
    CORSMiddleware, allow_origins=origins, allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-YouTube-Access-Token", "Stripe-Signature"],
)


@app.middleware("http")
async def refuse_media(request: Request, call_next):
    """Fail closed on binary/proxy attempts, even if a route is added later."""
    if request.method in ("POST", "PUT", "PATCH"):
        media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media_type not in ("application/json", ""):
            return JSONResponse(status_code=415, content={"detail": "Media uploads are disabled"})
        if request.headers.get("transfer-encoding"):
            return JSONResponse(status_code=411, content={"detail": "Chunked request bodies are disabled"})
        max_bytes = 262144 if request.url.path == "/v1/billing/stripe-webhook" else 32768
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) < 0 or int(content_length) > max_bytes:
                    return JSONResponse(status_code=413, content={"detail": "Only small JSON metadata is accepted"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
        elif request.method != "GET":
            return JSONResponse(status_code=411, content={"detail": "Content-Length is required"})
    return await call_next(request)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class OrgInput(BaseModel):
    org_id: UUID


class ChannelRegistration(BaseModel):
    org_id: UUID
    youtube_channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")


class SourceCreate(BaseModel):
    org_id: UUID
    youtube_channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")
    authorization_basis: str = Field(min_length=3, max_length=300)


class JobCreate(BaseModel):
    org_id: UUID
    channel_id: UUID
    client_key: str = Field(min_length=8, max_length=180)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1024, le=1073741824)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)


class ApprovalInput(BaseModel):
    org_id: UUID
    rights_confirmed: bool
    visibility: str = "private"


class PublicationComplete(BaseModel):
    org_id: UUID
    youtube_video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")


class PurchaseInput(BaseModel):
    org_id: UUID
    credits: int = Field(ge=100, le=100000)


def youtube_metadata(path: str, access_token: str | None, params: dict):
    if not access_token or len(access_token) > 4096 or any(c.isspace() for c in access_token):
        raise HTTPException(status_code=401, detail="Google authorization required")
    # Google access tokens are used only for this call and never written to DB/logs.
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            result = client.get(
                "https://www.googleapis.com/youtube/v3/" + path,
                params=params,
                headers={"Authorization": "Bearer " + access_token},
            )
        if result.status_code in (401, 403):
            raise HTTPException(401, "YouTube authorization expired or insufficient")
        result.raise_for_status()
        return result.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "YouTube metadata verification temporarily unavailable") from exc


def verify_channel(access_token: str | None, expected_id: str) -> dict:
    data = youtube_metadata("channels", access_token, {"part": "snippet", "mine": "true", "maxResults": 50})
    for item in data.get("items", []):
        if item.get("id") == expected_id:
            return {"id": expected_id, "title": str(item.get("snippet", {}).get("title") or "Canal")[:120]}
    raise HTTPException(403, "Selected channel does not belong to Google authorization")


def verify_uploaded_video(access_token: str | None, video_id: str, expected_channel: str) -> dict:
    data = youtube_metadata(
        "videos", access_token,
        {"part": "snippet,status", "id": video_id, "maxResults": 1},
    )
    rows = data.get("items") or []
    if (len(rows) != 1 or
            rows[0].get("snippet", {}).get("channelId") != expected_channel or
            rows[0].get("status", {}).get("privacyStatus") != "private"):
        raise HTTPException(409, "Video/channel/private status could not be verified")
    return rows[0]


def public_job(row):
    keys = ("id", "org_id", "channel_id", "title", "description", "status", "visibility",
            "credit_state", "youtube_video_id", "created_at", "updated_at", "last_error")
    return {key: row.get(key) for key in keys}


@app.get("/health")
def health():
    return {"ok": True, "mode": "browser-only-media", "media_storage": False}


@app.get("/ready")
def ready(conn=Depends(db_dep)):
    conn.execute("select 1")
    return {"ready": True}


@app.get("/v1/organizations")
def list_orgs(user: UUID = Depends(current_user), conn=Depends(db_dep)):
    return conn.execute(
        """select o.id,o.name,m.role from autoclips_saas.organizations o
           join autoclips_saas.memberships m on m.org_id=o.id
           where m.user_id=%s order by o.created_at""", (user,),
    ).fetchall()


@app.post("/v1/organizations", status_code=201)
def create_org(body: OrganizationCreate, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    with conn.transaction():
        org = conn.execute(
            "insert into autoclips_saas.organizations(name) values(%s) returning id,name",
            (body.name.strip(),),
        ).fetchone()
        conn.execute(
            "insert into autoclips_saas.memberships(org_id,user_id,role) values(%s,%s,'owner')",
            (org["id"], user),
        )
        conn.execute("insert into autoclips_saas.wallets(org_id) values(%s)", (org["id"],))
    return org


@app.get("/v1/wallet")
def wallet(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    row = conn.execute(
        "select available,reserved,total_purchased,updated_at from autoclips_saas.wallets where org_id=%s",
        (org_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Wallet not found")
    return {"org_id": org_id, "unit_price_cents": CREDIT_PRICE_CENTS, **row}


@app.get("/v1/channels")
def channels(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    return conn.execute(
        "select id,youtube_channel_id,title,active,created_at from autoclips_saas.channels where org_id=%s order by created_at",
        (org_id,),
    ).fetchall()


@app.post("/v1/channels/register")
def register_channel(
    body: ChannelRegistration,
    youtube_access_token: str | None = Header(default=None, alias="X-YouTube-Access-Token"),
    user: UUID = Depends(current_user), conn=Depends(db_dep),
):
    require_member(conn, body.org_id, user, ("owner", "admin"))
    identity = verify_channel(youtube_access_token, body.youtube_channel_id)
    with conn.transaction():
        row = conn.execute(
            """insert into autoclips_saas.channels(org_id,youtube_channel_id,title,active)
               values(%s,%s,%s,true)
               on conflict(org_id,youtube_channel_id)
               do update set title=excluded.title,active=true
               returning id,youtube_channel_id,title,active""",
            (body.org_id, identity["id"], identity["title"]),
        ).fetchone()
    return row


@app.post("/v1/channels/{channel_id}/disconnect")
def disconnect_channel(channel_id: UUID, body: OrgInput,
                       user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin"))
    with conn.transaction():
        channel = conn.execute(
            "select id from autoclips_saas.channels where id=%s and org_id=%s for update",
            (channel_id, body.org_id),
        ).fetchone()
        if not channel:
            raise HTTPException(404, "Channel not found")
        pending = conn.execute(
            """select count(*) as n from autoclips_saas.jobs
               where channel_id=%s and org_id=%s and status in ('queued','uploading','needs_reconciliation')""",
            (channel_id, body.org_id),
        ).fetchone()["n"]
        if pending:
            raise HTTPException(409, "Resolve pending uploads before disconnecting")
        conn.execute("update autoclips_saas.channels set active=false where id=%s", (channel_id,))
    return {"disconnected": True}


@app.get("/v1/sources")
def sources(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    return conn.execute(
        "select id,youtube_source_id,authorized_basis,created_at from autoclips_saas.sources where org_id=%s",
        (org_id,),
    ).fetchall()


@app.post("/v1/sources", status_code=201)
def create_source(body: SourceCreate, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    with conn.transaction():
        existing = conn.execute(
            "select id from autoclips_saas.sources where org_id=%s and youtube_source_id=%s",
            (body.org_id, body.youtube_channel_id),
        ).fetchone()
        if existing:
            return existing
        return conn.execute(
            """insert into autoclips_saas.sources(org_id,youtube_source_id,authorized_basis)
               values(%s,%s,%s) returning id""",
            (body.org_id, body.youtube_channel_id, body.authorization_basis.strip()),
        ).fetchone()


@app.get("/v1/sources/{source_id}/videos")
def source_videos(source_id: UUID, org_id: UUID,
                  user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    exists = conn.execute(
        "select id from autoclips_saas.sources where id=%s and org_id=%s",
        (source_id, org_id),
    ).fetchone()
    if not exists:
        raise HTTPException(404, "Source not found")
    return conn.execute(
        """select youtube_video_id,title,published_at,state,discovered_at
           from autoclips_saas.source_videos where source_id=%s and org_id=%s
           order by published_at desc nulls last limit 100""",
        (source_id, org_id),
    ).fetchall()


@app.post("/v1/sources/{source_id}/discover")
def discover_source(
    source_id: UUID, org_id: UUID,
    page_token: str = Query(default="", max_length=250),
    youtube_access_token: str | None = Header(default=None, alias="X-YouTube-Access-Token"),
    user: UUID = Depends(current_user), conn=Depends(db_dep),
):
    """Metadata ONLY, never download videos from the original YouTube channel."""
    require_member(conn, org_id, user, ("owner", "admin", "editor"))
    source = conn.execute(
        "select * from autoclips_saas.sources where id=%s and org_id=%s",
        (source_id, org_id),
    ).fetchone()
    if not source:
        raise HTTPException(404, "Source not found")
    data = youtube_metadata(
        "channels", youtube_access_token,
        {"part": "contentDetails", "id": source["youtube_source_id"], "maxResults": 1},
    )
    items = data.get("items") or []
    playlist = (items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if items else None)
    if not playlist:
        raise HTTPException(404, "Uploads playlist not available")
    params = {"part": "snippet,contentDetails", "playlistId": playlist, "maxResults": 25}
    if page_token:
        params["pageToken"] = page_token
    discovered = youtube_metadata("playlistItems", youtube_access_token, params)
    count = 0
    with conn.transaction():
        for item in discovered.get("items") or []:
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            conn.execute(
                """insert into autoclips_saas.source_videos
                   (org_id,source_id,youtube_video_id,title,published_at)
                   values(%s,%s,%s,%s,%s)
                   on conflict(org_id,source_id,youtube_video_id)
                   do update set title=excluded.title,published_at=excluded.published_at""",
                (org_id, source_id, video_id,
                 str(item.get("snippet", {}).get("title") or "")[:200],
                 item.get("contentDetails", {}).get("videoPublishedAt") or None),
            )
            count += 1
    return {"discovered": count, "next_page_token": discovered.get("nextPageToken"),
            "media_state": "awaiting_authorized_original"}


@app.get("/v1/jobs")
def jobs(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    rows = conn.execute(
        "select * from autoclips_saas.jobs where org_id=%s order by created_at desc limit 100",
        (org_id,),
    ).fetchall()
    return [public_job(row) for row in rows]


@app.post("/v1/jobs", status_code=201)
def create_job(body: JobCreate, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    channel = conn.execute(
        "select id,active from autoclips_saas.channels where id=%s and org_id=%s",
        (body.channel_id, body.org_id),
    ).fetchone()
    if not channel or not channel["active"]:
        raise HTTPException(404, "Selected channel unavailable")
    with conn.transaction():
        # ON CONFLICT DO NOTHING protects against concurrent duplicate browser retries.
        inserted = conn.execute(
            """insert into autoclips_saas.jobs
               (org_id,channel_id,client_key,expected_sha256,expected_bytes,title,description,status)
               values(%s,%s,%s,%s,%s,%s,%s,'ready')
               on conflict(org_id,client_key) do nothing returning *""",
            (body.org_id, body.channel_id, body.client_key, body.sha256, body.size_bytes,
             body.title.strip(), body.description),
        ).fetchone()
        if inserted:
            return public_job(inserted)
        previous = conn.execute(
            """select * from autoclips_saas.jobs where org_id=%s and client_key=%s for update""",
            (body.org_id, body.client_key),
        ).fetchone()
        if not previous:
            raise HTTPException(409, "Publication key conflict; refresh before retrying")
        if (previous["expected_sha256"] != body.sha256 or
                previous["channel_id"] != body.channel_id or
                previous["expected_bytes"] != body.size_bytes):
            raise HTTPException(409, "Idempotency key already used with other media or channel")
        return public_job(previous)


@app.post("/v1/jobs/{job_id}/approve")
def approve_job(job_id: UUID, body: ApprovalInput, user: UUID = Depends(current_user),
                conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    if not body.rights_confirmed:
        raise HTTPException(400, "Explicit media rights confirmation required")
    if body.visibility != "private":
        raise HTTPException(400, "Only private uploads can be initiated")
    with conn.transaction():
        return public_job(reserve_credit(conn, body.org_id, job_id, user))


@app.post("/v1/jobs/{job_id}/begin")
def begin_upload(job_id: UUID, body: OrgInput, user: UUID = Depends(current_user),
                 conn=Depends(db_dep)):
    """One-way transition BEFORE initiating direct client-side YouTube upload."""
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    with conn.transaction():
        row = conn.execute(
            """update autoclips_saas.jobs set status='uploading',attempt_count=attempt_count+1,
               updated_at=now() where id=%s and org_id=%s and status='queued'
               and credit_state='reserved' and rights_confirmed=true
               returning *""", (job_id, body.org_id),
        ).fetchone()
        if not row:
            raise HTTPException(409, "Upload already initiated, cancelled or unavailable: reconcile first")
    return public_job(row)


@app.post("/v1/jobs/{job_id}/uncertain")
def mark_uncertain(job_id: UUID, body: OrgInput, user: UUID = Depends(current_user),
                   conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    with conn.transaction():
        row = conn.execute(
            """update autoclips_saas.jobs set status='needs_reconciliation',
               last_error='Client upload status uncertain; manual YouTube verification required',
               updated_at=now() where id=%s and org_id=%s and status='uploading'
               returning *""", (job_id, body.org_id),
        ).fetchone()
        if not row:
            row = conn.execute(
                "select * from autoclips_saas.jobs where id=%s and org_id=%s",
                (job_id, body.org_id),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
    return public_job(row)


@app.post("/v1/jobs/{job_id}/complete")
def complete_upload(
    job_id: UUID, body: PublicationComplete,
    youtube_access_token: str | None = Header(default=None, alias="X-YouTube-Access-Token"),
    user: UUID = Depends(current_user), conn=Depends(db_dep),
):
    """Verify Google private video and expected channel; never receive video bytes."""
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    job = conn.execute(
        """select j.*,c.youtube_channel_id from autoclips_saas.jobs j
           join autoclips_saas.channels c on c.id=j.channel_id and c.org_id=j.org_id
           where j.id=%s and j.org_id=%s""", (job_id, body.org_id),
    ).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] == "published" and job["youtube_video_id"] == body.youtube_video_id:
        return public_job(job)
    if job["status"] not in ("uploading", "needs_reconciliation"):
        raise HTTPException(409, "Upload not started or publication already completed")
    verify_uploaded_video(youtube_access_token, body.youtube_video_id, job["youtube_channel_id"])
    with conn.transaction():
        return public_job(capture_credit(conn, body.org_id, job_id, body.youtube_video_id))


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, body: OrgInput, user: UUID = Depends(current_user),
               conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    with conn.transaction():
        conn.execute(
            "select org_id from autoclips_saas.wallets where org_id=%s for update",
            (body.org_id,),
        )
        job = conn.execute(
            "select * from autoclips_saas.jobs where id=%s and org_id=%s for update",
            (job_id, body.org_id),
        ).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] == "queued":
            job = release_credit(conn, body.org_id, job_id)
        elif job["status"] == "ready":
            conn.execute("update autoclips_saas.jobs set status='cancelled' where id=%s", (job_id,))
            job["status"] = "cancelled"
        elif job["status"] != "cancelled":
            raise HTTPException(409, "Upload may have started; cannot automatically refund")
    return public_job(job)


@app.post("/v1/billing/checkout")
def checkout(body: PurchaseInput, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin"))
    stripe.api_key = config("STRIPE_SECRET_KEY")
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=config("BILLING_SUCCESS_URL") + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=config("BILLING_CANCEL_URL"),
            client_reference_id=str(user),
            metadata={"org_id": str(body.org_id), "credits": str(body.credits)},
            line_items=[{"price_data": {
                "currency": "brl", "unit_amount": CREDIT_PRICE_CENTS,
                "product_data": {"name": "AutoClips - crédito para publicação"}
            }, "quantity": body.credits}],
        )
    except stripe.StripeError as exc:
        raise HTTPException(502, "Checkout unavailable") from exc
    with conn.transaction():
        conn.execute(
            """insert into autoclips_saas.stripe_checkouts(session_id,org_id,user_id,credits,amount_cents)
               values(%s,%s,%s,%s,%s)""",
            (session.id, body.org_id, user, body.credits, body.credits * CREDIT_PRICE_CENTS),
        )
    return {"checkout_url": session.url, "credits": body.credits, "amount_cents": body.credits * CREDIT_PRICE_CENTS}


@app.post("/v1/billing/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")):
    if not stripe_signature:
        raise HTTPException(400, "Missing Stripe signature")
    raw = await request.body()
    try:
        event = stripe.Webhook.construct_event(raw, stripe_signature, config("STRIPE_WEBHOOK_SECRET"))
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid Stripe signature")
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        paid = event["data"]["object"]
        if paid.get("payment_status") == "paid":
            with database() as conn:
                with conn.transaction():
                    grant_paid_credits(
                        conn, paid["id"], paid.get("amount_total") or 0,
                        paid.get("currency") or "",
                    )
    return {"received": True}
