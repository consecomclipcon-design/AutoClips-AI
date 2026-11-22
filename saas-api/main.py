"""AutoClips SaaS API (staging): authorized media only, private YouTube uploads.

Requires schema.sql + external Supabase Auth, Google OAuth, S3 and Stripe secrets.
No secret is returned to the browser. No publication occurs in this web process.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

import boto3
import httpx
import psycopg
import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from core import (
    CREDIT_PRICE_CENTS, YOUTUBE_SCOPES, capture_credit, config,
    current_user, database, db_dep, digest_token, encrypt_token,
    decrypt_token, grant_paid_credits, iso_now, release_credit,
    require_member, reserve_credit,
)

app = FastAPI(title="AutoClips SaaS (staging)", docs_url="/docs" if os.getenv("ENABLE_API_DOCS") == "1" else None)
origins = [origin.strip() for origin in os.getenv("APP_ORIGINS", "").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "Stripe-Signature"])


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)



class SourceCreate(BaseModel):
    org_id: UUID
    youtube_channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")
    authorization_basis: str = Field(min_length=3, max_length=300)


class ExportCreate(BaseModel):
    org_id: UUID
    channel_id: UUID
    client_key: str = Field(min_length=8, max_length=180)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1024, le=1_073_741_824)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)


class OrgInput(BaseModel):
    org_id: UUID


class ApprovalInput(BaseModel):
    org_id: UUID
    rights_confirmed: bool
    visibility: str = "private"


class PurchaseInput(BaseModel):
    org_id: UUID
    credits: int = Field(ge=100, le=100000)


def s3():
    return boto3.client(
        "s3", region_name=os.getenv("S3_REGION") or "us-east-1",
        endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        aws_access_key_id=config("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=config("S3_SECRET_ACCESS_KEY"),
    )


def public_job(row):
    """Never return secrets or full storage paths to unauthorized users."""
    fields = ("id", "org_id", "channel_id", "title", "status", "visibility",
              "credit_state", "youtube_video_id", "created_at", "updated_at", "last_error")
    return {field: row.get(field) for field in fields}


@app.get("/health")
def health():
    return {"ok": True, "service": "autoclips-saas-api", "publishing": "worker-only"}


@app.get("/v1/organizations")
def organizations(user: UUID = Depends(current_user), conn=Depends(db_dep)):
    return conn.execute(
        """select o.id,o.name,m.role from autoclips_saas.organizations o
           join autoclips_saas.memberships m on m.org_id=o.id where m.user_id=%s
           order by o.created_at""", (user,)
    ).fetchall()


@app.post("/v1/organizations", status_code=201)
def create_org(body: OrganizationCreate, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    with conn.transaction():
        row = conn.execute(
            "insert into autoclips_saas.organizations(name) values(%s) returning id,name",
            (body.name.strip(),)
        ).fetchone()
        conn.execute(
            "insert into autoclips_saas.memberships(org_id,user_id,role) values(%s,%s,'owner')",
            (row["id"], user),
        )
        conn.execute("insert into autoclips_saas.wallets(org_id) values(%s)", (row["id"],))
    return row


@app.get("/v1/wallet")
def wallet(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    row = conn.execute(
        "select available,reserved,total_purchased,updated_at from autoclips_saas.wallets where org_id=%s",
        (org_id,),
    ).fetchone()
    return {"org_id": org_id, "unit_price_cents": CREDIT_PRICE_CENTS, **(row or {})}


@app.get("/v1/channels")
def channels(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    return conn.execute(
        """select id,youtube_channel_id,title,active,created_at
           from autoclips_saas.channels where org_id=%s order by created_at""", (org_id,)
    ).fetchall()


@app.post("/v1/channels/connect")
def connect_google(body: OrgInput, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin"))
    state = secrets.token_urlsafe(40)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with conn.transaction():
        conn.execute(
            """insert into autoclips_saas.oauth_states(state_hash,org_id,user_id,code_verifier,expires_at)
               values(%s,%s,%s,%s,%s)""",
            (digest_token(state), body.org_id, user, verifier, iso_now() + timedelta(minutes=10)),
        )
    params = {
        "client_id": config("GOOGLE_CLIENT_ID"),
        "redirect_uri": config("GOOGLE_REDIRECT_URI"),
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@app.get("/v1/oauth/google/callback")
def google_callback(state: str = Query(min_length=20, max_length=256),
                    code: str | None = Query(default=None),
                    error: str | None = Query(default=None),
                    conn=Depends(db_dep)):
    frontend = config("APP_SUCCESS_URL")
    if error or not code:
        return RedirectResponse(frontend + ("&" if "?" in frontend else "?") + "google=denied", status_code=303)
    with conn.transaction():
        row = conn.execute(
            """select state_hash,org_id,user_id,code_verifier from autoclips_saas.oauth_states
               where state_hash=%s and used_at is null and expires_at>now() for update""",
            (digest_token(state),),
        ).fetchone()
        if not row:
            raise HTTPException(400, "Expired OAuth state")
        conn.execute("update autoclips_saas.oauth_states set used_at=now() where state_hash=%s", (row["state_hash"],))
    try:
        with httpx.Client(timeout=20.0) as client:
            token_res = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config("GOOGLE_CLIENT_ID"),
                    "client_secret": config("GOOGLE_CLIENT_SECRET"),
                    "code": code,
                    "code_verifier": row["code_verifier"],
                    "grant_type": "authorization_code",
                    "redirect_uri": config("GOOGLE_REDIRECT_URI"),
                },
            )
            token_res.raise_for_status()
            token = token_res.json()
            scopes = set(token.get("scope", "").split())
            if not set(YOUTUBE_SCOPES).issubset(scopes):
                raise HTTPException(403, "YouTube read and upload permissions are required")
            channel_res = client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true", "maxResults": 50},
                headers={"Authorization": "Bearer " + token["access_token"]},
            )
            channel_res.raise_for_status()
            items = channel_res.json().get("items", [])
        if not items:
            raise HTTPException(400, "No YouTube channel accessible with this account")
        if not token.get("refresh_token"):
            raise HTTPException(400, "Google did not return offline access; disconnect and re-consent")
        cipher = encrypt_token(token["refresh_token"])
        with conn.transaction():
            for item in items:
                channel_id = item.get("id", "")
                title = item.get("snippet", {}).get("title", "Canal")
                if not channel_id.startswith("UC"):
                    continue
                conn.execute(
                    """insert into autoclips_saas.channels
                       (org_id,youtube_channel_id,title,token_ciphertext,scopes,active)
                       values(%s,%s,%s,%s,%s,true)
                       on conflict(org_id,youtube_channel_id) do update
                       set title=excluded.title,token_ciphertext=excluded.token_ciphertext,
                           scopes=excluded.scopes,active=true""",
                    (row["org_id"], channel_id, title, cipher, " ".join(YOUTUBE_SCOPES)),
                )
        return RedirectResponse(frontend + ("&" if "?" in frontend else "?") + "google=connected", status_code=303)
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(502, "Google OAuth channel verification failed") from exc


@app.post("/v1/channels/{channel_id}/disconnect")
def disconnect(channel_id: UUID, body: OrgInput,
               user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin"))
    with conn.transaction():
        row = conn.execute(
            """select id from autoclips_saas.channels where id=%s and org_id=%s for update""",
            (channel_id, body.org_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Channel not found")
        pending = conn.execute(
            """select count(*) as n from autoclips_saas.jobs
               where org_id=%s and channel_id=%s and status in ('queued','uploading','needs_reconciliation')""",
            (body.org_id, channel_id),
        ).fetchone()["n"]
        if pending:
            raise HTTPException(409, "Resolve pending publications before disconnecting this channel")
        conn.execute(
            "update autoclips_saas.channels set active=false,token_ciphertext='' where id=%s",
            (channel_id,),
        )
    return {"disconnected": True}


@app.get("/v1/sources")
def sources(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    return conn.execute(
        """select id,youtube_source_id,authorized_basis,created_at
           from autoclips_saas.sources where org_id=%s order by created_at desc""",
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
    row = conn.execute(
        "select id from autoclips_saas.sources where id=%s and org_id=%s", (source_id, org_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Source not found")
    return conn.execute(
        """select id,youtube_video_id,title,published_at,state,discovered_at
           from autoclips_saas.source_videos where org_id=%s and source_id=%s
           order by published_at desc nulls last limit 100""",
        (org_id, source_id),
    ).fetchall()


@app.post("/v1/sources/{source_id}/discover")
def discover_source(source_id: UUID, org_id: UUID, connected_channel_id: UUID,
                    page_token: str = Query(default="", max_length=250),
                    user: UUID = Depends(current_user), conn=Depends(db_dep)):
    """Metadata discovery only. No audiovisual download; each original awaits authorized file."""
    require_member(conn, org_id, user, ("owner", "admin", "editor"))
    source = conn.execute(
        "select * from autoclips_saas.sources where id=%s and org_id=%s",
        (source_id, org_id),
    ).fetchone()
    channel = conn.execute(
        "select * from autoclips_saas.channels where id=%s and org_id=%s and active=true",
        (connected_channel_id, org_id),
    ).fetchone()
    if source is None or channel is None:
        raise HTTPException(404, "Source or channel not found")
    try:
        from worker import youtube_client
        youtube = youtube_client(channel)
        info = youtube.channels().list(part="contentDetails", id=source["youtube_source_id"]).execute()
        items = info.get("items") or []
        if not items:
            raise HTTPException(404, "Original channel not available")
        uploads_playlist = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads_playlist:
            raise HTTPException(404, "Uploads playlist is not available")
        opts = {"part": "snippet,contentDetails", "playlistId": uploads_playlist, "maxResults": 25}
        if page_token:
            opts["pageToken"] = page_token
        discovered = youtube.playlistItems().list(**opts).execute()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "YouTube metadata discovery failed") from exc
    accepted = 0
    with conn.transaction():
        for item in discovered.get("items") or []:
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            title = item.get("snippet", {}).get("title", "")[:200]
            published_at = item.get("contentDetails", {}).get("videoPublishedAt") or None
            conn.execute(
                """insert into autoclips_saas.source_videos
                   (org_id,source_id,youtube_video_id,title,published_at)
                   values(%s,%s,%s,%s,%s)
                   on conflict(org_id,source_id,youtube_video_id)
                   do update set title=excluded.title,published_at=excluded.published_at""",
                (org_id, source_id, video_id, title, published_at),
            )
            accepted += 1
    return {"discovered": accepted, "next_page_token": discovered.get("nextPageToken"),
            "media_state": "awaiting_authorized_original"}


@app.post("/v1/exports", status_code=201)
def create_export(body: ExportCreate, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    channel = conn.execute(
        "select active from autoclips_saas.channels where id=%s and org_id=%s",
        (body.channel_id, body.org_id),
    ).fetchone()
    if not channel or not channel["active"]:
        raise HTTPException(404, "Channel not available")
    # Client-chosen idempotency key prevents creating duplicates from repeated requests.
    with conn.transaction():
        old = conn.execute(
            "select * from autoclips_saas.jobs where org_id=%s and client_key=%s for update",
            (body.org_id, body.client_key),
        ).fetchone()
        if old is not None:
            if old["expected_sha256"] != body.sha256 or old["channel_id"] != body.channel_id:
                raise HTTPException(409, "Idempotency key reused with different media/channel")
            job = old
        else:
            # The final object key is server-generated; clients may upload only this signed object.
            job_id = __import__("uuid").uuid4()
            object_key = "saas/" + str(body.org_id) + "/final/" + str(job_id) + ".mp4"
            job = conn.execute(
                """insert into autoclips_saas.jobs
                   (id,org_id,channel_id,client_key,object_key,expected_sha256,expected_bytes,title,description)
                   values(%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                (job_id, body.org_id, body.channel_id, body.client_key, object_key,
                 body.sha256, body.size_bytes, body.title, body.description),
            ).fetchone()
    if job["status"] != "awaiting_media":
        return {"job": public_job(job), "already_uploaded": True}
    checksum_b64 = base64.b64encode(bytes.fromhex(job["expected_sha256"])).decode()
    url = s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": config("S3_BUCKET"),
            "Key": job["object_key"],
            "ContentType": "video/mp4",
            "ChecksumSHA256": checksum_b64,
        },
        ExpiresIn=900,
        HttpMethod="PUT",
    )
    return {
        "job": public_job(job),
        "upload_url": url,
        "required_headers": {"Content-Type": "video/mp4", "x-amz-checksum-sha256": checksum_b64},
        "expires_in_seconds": 900,
    }


@app.post("/v1/exports/{job_id}/complete")
def complete_export(job_id: UUID, body: OrgInput,
                    user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    row = conn.execute(
        "select * from autoclips_saas.jobs where id=%s and org_id=%s",
        (job_id, body.org_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    if row["status"] == "ready":
        return public_job(row)
    if row["status"] != "awaiting_media":
        raise HTTPException(409, "Job is not waiting for a file")
    try:
        item = s3().head_object(Bucket=config("S3_BUCKET"), Key=row["object_key"])
    except Exception:
        raise HTTPException(409, "Upload not confirmed by private storage")
    if item.get("ContentLength") != row["expected_bytes"]:
        raise HTTPException(409, "Stored media size does not match expected bytes")
    if (item.get("ContentType") or "").split(";")[0] != "video/mp4":
        raise HTTPException(409, "Expected MP4 media")
    with conn.transaction():
        result = conn.execute(
            """update autoclips_saas.jobs set status='ready',verified_bytes=%s,updated_at=now()
               where id=%s and org_id=%s and status='awaiting_media' returning *""",
            (item["ContentLength"], job_id, body.org_id),
        ).fetchone()
    return public_job(result or row)


@app.get("/v1/jobs")
def jobs(org_id: UUID, user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, org_id, user)
    rows = conn.execute(
        """select * from autoclips_saas.jobs where org_id=%s
           order by created_at desc limit 100""", (org_id,),
    ).fetchall()
    return [public_job(r) for r in rows]


@app.get("/v1/jobs/{job_id}/preview")
def get_private_preview(job_id: UUID, org_id: UUID,
                        user: UUID = Depends(current_user), conn=Depends(db_dep)):
    """Short-lived link for mobile review of the final MP4 (never the long original)."""
    require_member(conn, org_id, user)
    row = conn.execute(
        "select object_key,status from autoclips_saas.jobs where id=%s and org_id=%s",
        (job_id, org_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Video not found")
    if row["status"] == "awaiting_media":
        raise HTTPException(409, "Final MP4 has not been uploaded")
    try:
        url = s3().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": config("S3_BUCKET"),
                "Key": row["object_key"],
                "ResponseContentType": "video/mp4",
            },
            ExpiresIn=180,
            HttpMethod="GET",
        )
        return {"preview_url": url, "expires_in_seconds": 180}
    except Exception as exc:
        raise HTTPException(502, "Private preview unavailable") from exc


@app.post("/v1/jobs/{job_id}/approve")
def approve_job(job_id: UUID, body: ApprovalInput,
                user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    if not body.rights_confirmed:
        raise HTTPException(400, "Explicit confirmation of media rights is required")
    if body.visibility != "private":
        raise HTTPException(400, "Only private uploads are permitted in the initial release")
    with conn.transaction():
        job = reserve_credit(conn, body.org_id, job_id, user)
    return public_job(job)


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, body: OrgInput,
               user: UUID = Depends(current_user), conn=Depends(db_dep)):
    require_member(conn, body.org_id, user, ("owner", "admin", "editor"))
    with conn.transaction():
        job = conn.execute(
            "select * from autoclips_saas.jobs where org_id=%s and id=%s for update",
            (body.org_id, job_id),
        ).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] == "queued":
            job = release_credit(conn, body.org_id, job_id)
        elif job["status"] in ("awaiting_media", "ready"):
            conn.execute("update autoclips_saas.jobs set status='cancelled' where id=%s", (job_id,))
            job["status"] = "cancelled"
        elif job["status"] != "cancelled":
            raise HTTPException(409, "Cannot cancel a started or uncertain YouTube upload")
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
                "product_data": {"name": "AutoClips - 1 credito de publicacao privada"}
            }, "quantity": body.credits}],
        )
    except stripe.StripeError as exc:
        raise HTTPException(502, "Checkout could not be created") from exc
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
        session = event["data"]["object"]
        if session.get("payment_status") == "paid":
            with database() as conn:
                with conn.transaction():
                    grant_paid_credits(
                        conn, session["id"], session.get("amount_total") or 0,
                        session.get("currency") or "",
                    )
    return {"received": True}
