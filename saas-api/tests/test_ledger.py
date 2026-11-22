"""Run only against the isolated CI Postgres database, never production."""
import os
from uuid import uuid4

import pytest
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException

from core import (
    capture_credit, grant_paid_credits, release_credit, require_member, reserve_credit,
)

@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row) as db:
        with db.transaction():
            db.execute("truncate autoclips_saas.organizations cascade")
        yield db


def setup_org(conn, credits=0):
    user_id = uuid4()
    with conn.transaction():
        org = conn.execute(
            "insert into autoclips_saas.organizations(name) values('Test tenant') returning id"
        ).fetchone()["id"]
        conn.execute(
            "insert into autoclips_saas.memberships(org_id,user_id,role) values(%s,%s,'owner')",
            (org, user_id),
        )
        conn.execute(
            "insert into autoclips_saas.wallets(org_id,available,total_purchased) values(%s,%s,%s)",
            (org, credits, credits),
        )
        channel = conn.execute(
            """insert into autoclips_saas.channels(org_id,youtube_channel_id,title)
               values(%s,%s,'Test channel') returning id""",
            (org, "UC" + uuid4().hex[:22]),
        ).fetchone()["id"]
    return org, user_id, channel


def setup_job(conn, org, channel, key="local-file-unique"):
    with conn.transaction():
        return conn.execute(
            """insert into autoclips_saas.jobs
               (org_id,channel_id,client_key,expected_sha256,expected_bytes,title,status)
               values(%s,%s,%s,%s,10000,'Test clip','ready') returning id""",
            (org, channel, key, "a" * 64),
        ).fetchone()["id"]


def wallet(conn, org):
    row = conn.execute(
        "select available,reserved from autoclips_saas.wallets where org_id=%s", (org,)
    ).fetchone()
    return row["available"], row["reserved"]


def test_reserve_capture_once(conn):
    org, user, channel = setup_org(conn, credits=1)
    job = setup_job(conn, org, channel)
    with conn.transaction():
        reserve_credit(conn, org, job, user)
    assert wallet(conn, org) == (0, 1)
    with conn.transaction():
        reserve_credit(conn, org, job, user)
    assert wallet(conn, org) == (0, 1)
    with conn.transaction():
        conn.execute("update autoclips_saas.jobs set status='uploading' where id=%s", (job,))
        capture_credit(conn, org, job, "video_ABCD")
    assert wallet(conn, org) == (0, 0)
    with conn.transaction():
        capture_credit(conn, org, job, "video_ABCD")
    assert wallet(conn, org) == (0, 0)
    rows = conn.execute(
        "select kind,count(*) from autoclips_saas.credit_events where job_id=%s group by kind", (job,)
    ).fetchall()
    assert sorted((r["kind"], r["count"]) for r in rows) == [("capture", 1), ("reserve", 1)]


def test_one_credit_two_jobs_prevents_overspend(conn):
    org, user, channel = setup_org(conn, credits=1)
    a, b = setup_job(conn, org, channel, "client-key-a"), setup_job(conn, org, channel, "client-key-b")
    with conn.transaction():
        reserve_credit(conn, org, a, user)
    with pytest.raises(HTTPException) as exc:
        with conn.transaction():
            reserve_credit(conn, org, b, user)
    assert exc.value.status_code == 402
    assert wallet(conn, org) == (0, 1)


def test_cancel_refunds_only_queued(conn):
    org, user, channel = setup_org(conn, credits=1)
    job = setup_job(conn, org, channel)
    with conn.transaction():
        reserve_credit(conn, org, job, user)
    with conn.transaction():
        release_credit(conn, org, job)
    assert wallet(conn, org) == (1, 0)
    with conn.transaction():
        release_credit(conn, org, job)
    assert wallet(conn, org) == (1, 0)


def test_no_refund_after_upload_starts(conn):
    org, user, channel = setup_org(conn, credits=1)
    job = setup_job(conn, org, channel)
    with conn.transaction():
        reserve_credit(conn, org, job, user)
        conn.execute("update autoclips_saas.jobs set status='uploading' where id=%s", (job,))
    with pytest.raises(HTTPException) as exc:
        with conn.transaction():
            release_credit(conn, org, job)
    assert exc.value.status_code == 409
    assert wallet(conn, org) == (0, 1)


def test_stripe_checkout_is_idempotent(conn):
    org, user, _ = setup_org(conn, credits=0)
    with conn.transaction():
        conn.execute(
            """insert into autoclips_saas.stripe_checkouts(session_id,org_id,user_id,credits,amount_cents)
               values('cs_test_once',%s,%s,100,1500)""", (org, user),
        )
        assert grant_paid_credits(conn, "cs_test_once", 1500, "brl") is True
    with conn.transaction():
        assert grant_paid_credits(conn, "cs_test_once", 1500, "brl") is False
    assert wallet(conn, org) == (100, 0)


def test_cross_tenant_and_channel_fk(conn):
    org, user, channel = setup_org(conn, credits=100)
    other, other_user, other_channel = setup_org(conn, credits=0)
    with pytest.raises(HTTPException):
        require_member(conn, other, user)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            setup_job(conn, org, other_channel, "cross-tenant-not-allowed")


def test_paid_amount_must_match_exactly(conn):
    org, user, _ = setup_org(conn, credits=0)
    with conn.transaction():
        conn.execute(
            """insert into autoclips_saas.stripe_checkouts(session_id,org_id,user_id,credits,amount_cents)
               values('cs_test_wrong_amount',%s,%s,100,1500)""", (org, user),
        )
    with pytest.raises(HTTPException) as err:
        with conn.transaction():
            grant_paid_credits(conn, "cs_test_wrong_amount", 1400, "brl")
    assert err.value.status_code == 400
    assert wallet(conn, org) == (0, 0)
