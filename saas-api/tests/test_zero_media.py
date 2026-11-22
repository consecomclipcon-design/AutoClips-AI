"""Zero-media API: no application endpoint should accept binary video bytes."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from core import capture_credit, reserve_credit
from test_ledger import setup_org, setup_job, wallet, conn


def test_media_upload_is_blocked_by_middleware():
    client = TestClient(main.app)
    response = client.post(
        "/v1/jobs", content=b"fake mp4 bytes",
        headers={"content-type": "video/mp4"},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "Media uploads are disabled"


def test_large_json_rejected_before_auth():
    client = TestClient(main.app)
    payload = '{"data":"' + ("A" * 100000) + '"}'
    response = client.post(
        "/v1/jobs", content=payload.encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_no_storage_or_media_proxy_routes():
    paths = {route.path for route in main.app.routes}
    assert "/v1/exports" not in paths
    assert "/v1/exports/{job_id}/complete" not in paths
    assert "/v1/jobs/{job_id}/preview" not in paths
    assert not any("storage" in path or "download" in path or "media" in path for path in paths)


def test_channel_registration_verifies_google_without_storing_token(conn, monkeypatch):
    org, user, _ = setup_org(conn)
    google_id = "UC" + uuid4().hex[:22]
    seen = []

    def fake_verify(token, expected_id):
        seen.append((token, expected_id))
        return {"id": expected_id, "title": "Owner Channel"}

    monkeypatch.setattr(main, "verify_channel", fake_verify)
    result = main.register_channel(
        main.ChannelRegistration(org_id=org, youtube_channel_id=google_id),
        youtube_access_token="transient-google-token",
        user=user, conn=conn,
    )
    assert result["youtube_channel_id"] == google_id
    assert seen == [("transient-google-token", google_id)]
    # DB only records channel metadata, never OAuth credentials.
    fields = conn.execute(
        "select column_name from information_schema.columns where table_schema='autoclips_saas' and table_name='channels'"
    ).fetchall()
    columns = {row["column_name"] for row in fields}
    assert "token_ciphertext" not in columns
    assert "refresh_token" not in columns
    assert "scopes" not in columns


def test_server_verifies_real_channel_before_credit_capture(conn, monkeypatch):
    org, user, channel = setup_org(conn, credits=1)
    job = setup_job(conn, org, channel)
    with conn.transaction():
        reserve_credit(conn, org, job, user)
    main.begin_upload(job, main.OrgInput(org_id=org), user=user, conn=conn)
    verified = []

    def fake_google(access_token, video_id, channel_id):
        verified.append((access_token, video_id, channel_id))
        return {"id": video_id}
    monkeypatch.setattr(main, "verify_uploaded_video", fake_google)
    video_id = "aBcDefGh123"
    row = main.complete_upload(
        job,
        main.PublicationComplete(org_id=org, youtube_video_id=video_id),
        youtube_access_token="short-lived-google-token", user=user, conn=conn,
    )
    assert row["status"] == "published"
    assert row["credit_state"] == "captured"
    assert len(verified) == 1
    assert verified[0][0] == "short-lived-google-token"
    assert verified[0][1] == video_id
    assert wallet(conn, org) == (0, 0)
    # Duplicate confirmations must never debit credits again.
    again = main.complete_upload(
        job,
        main.PublicationComplete(org_id=org, youtube_video_id=video_id),
        youtube_access_token="short-lived-google-token", user=user, conn=conn,
    )
    assert again["status"] == "published"
    assert wallet(conn, org) == (0, 0)


def test_upload_started_once_and_never_automatically_retries(conn):
    org, user, channel = setup_org(conn, credits=1)
    job = setup_job(conn, org, channel)
    with conn.transaction():
        reserve_credit(conn, org, job, user)
    first = main.begin_upload(job, main.OrgInput(org_id=org), user=user, conn=conn)
    assert first["status"] == "uploading"
    with pytest.raises(HTTPException) as exc:
        main.begin_upload(job, main.OrgInput(org_id=org), user=user, conn=conn)
    assert exc.value.status_code == 409
    result = main.mark_uncertain(job, main.OrgInput(org_id=org), user=user, conn=conn)
    assert result["status"] == "needs_reconciliation"
    assert wallet(conn, org) == (0, 1)
    with pytest.raises(HTTPException):
        main.cancel_job(job, main.OrgInput(org_id=org), user=user, conn=conn)
