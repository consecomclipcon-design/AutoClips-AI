"""Dedicated queue worker. It never automatically retries an ambiguous YouTube upload.

Start separately from API after setting DATABASE_URL, S3_* and Google OAuth secrets.
Uses private, approved jobs only and confirms the destination channel before upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import UUID

import boto3
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core import (
    YOUTUBE_SCOPES, capture_credit, config, database, decrypt_token, release_credit,
)


def claim_job():
    with database() as conn:
        with conn.transaction():
            row = conn.execute(
                """select id from autoclips_saas.jobs where status='queued'
                   order by created_at for update skip locked limit 1"""
            ).fetchone()
            if row is None:
                return None
            return conn.execute(
                """update autoclips_saas.jobs set status='uploading',attempt_count=attempt_count+1,
                   locked_at=now(),updated_at=now() where id=%s and status='queued'
                   returning *""", (row["id"],),
            ).fetchone()


def storage_client():
    return boto3.client(
        "s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        region_name=os.getenv("S3_REGION") or "us-east-1",
        aws_access_key_id=config("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=config("S3_SECRET_ACCESS_KEY"),
    )


def verify_media(path: str, expected_sha256: str, expected_bytes: int):
    actual_bytes = os.stat(path).st_size
    if actual_bytes != expected_bytes:
        raise ValueError("downloaded media size mismatch")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(2 ** 20), b""):
            h.update(piece)
    if h.hexdigest() != expected_sha256:
        raise ValueError("downloaded media SHA256 mismatch")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
        capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos or not audios:
        raise ValueError("Expected both video and audio tracks")
    width, height = videos[0].get("width", 0), videos[0].get("height", 0)
    if width <= 0 or height <= 0 or abs(width / height - 9 / 16) > 0.02:
        raise ValueError("Expected a 9:16 vertical MP4")
    duration = float(payload.get("format", {}).get("duration") or 0)
    if not (0 < duration <= 180.5):
        raise ValueError("MP4 duration must be within 180 seconds")
    return {
        "video_codec": videos[0].get("codec_name"),
        "audio_codec": audios[0].get("codec_name"),
        "width": width, "height": height, "duration": duration,
    }


def normalize_media(path: str, metadata: dict, directory: str) -> str:
    """Final-clip codec fallback ONLY. Never transcode a long source on the server.

    Chromium sometimes wraps VP9/Opus in MP4 despite advertising an MP4 MIME.
    This function ensures the YouTube uploader receives H.264/AAC in a real MP4.
    Off by default: enable explicitly in staging after measuring CPU/cost.
    """
    if metadata["video_codec"] == "h264" and metadata["audio_codec"] == "aac":
        return path
    if os.getenv("ALLOW_SERVER_CODEC_FALLBACK", "0") != "1":
        raise ValueError("Browser produced incompatible MP4 codecs; enable tested final-clip fallback")
    output = str(Path(directory) / "youtube-compatible.mp4")
    args = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", path, "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-pix_fmt", "yuv420p", "-threads", "2",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", output,
    ]
    subprocess.run(args, capture_output=True, check=True, timeout=900)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,codec_type,width,height", "-of", "json", output],
        capture_output=True, text=True, check=True, timeout=30,
    )
    parsed = json.loads(probe.stdout).get("streams", [])
    video = next((x for x in parsed if x.get("codec_type") == "video"), {})
    audio = next((x for x in parsed if x.get("codec_type") == "audio"), {})
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        raise ValueError("Post-encode codec validation failed")
    if video.get("width") != metadata["width"] or video.get("height") != metadata["height"]:
        raise ValueError("Post-encode dimensions changed unexpectedly")
    return output


def preflight_abort(job, error: Exception):
    """A verified preflight failure occurred BEFORE any YouTube write was attempted."""
    with database() as conn:
        with conn.transaction():
            conn.execute("select org_id from autoclips_saas.wallets where org_id=%s for update", (job["org_id"],))
            row = conn.execute(
                "select status,credit_state from autoclips_saas.jobs where id=%s for update",
                (job["id"],),
            ).fetchone()
            if row and row["status"] == "uploading" and row["credit_state"] == "reserved":
                conn.execute(
                    "update autoclips_saas.jobs set status='queued',last_error=%s where id=%s",
                    ("Preflight blocked (" + type(error).__name__ + "); check private worker logs without tokens", job["id"]),
                )
                release_credit(conn, job["org_id"], job["id"])


def mark_uncertain(job, error: Exception):
    """Never repeat an upload once a YouTube request may have been sent."""
    with database() as conn:
        with conn.transaction():
            conn.execute(
                """update autoclips_saas.jobs set status='needs_reconciliation',
                   last_error=%s,updated_at=now() where id=%s and status='uploading'""",
                ("Upload result uncertain (" + type(error).__name__ + "); manual reconciliation required", job["id"]),
            )


def youtube_client(channel):
    credentials = Credentials(
        token=None,
        refresh_token=decrypt_token(channel["token_ciphertext"]),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config("GOOGLE_CLIENT_ID"),
        client_secret=config("GOOGLE_CLIENT_SECRET"),
        scopes=YOUTUBE_SCOPES,
    )
    credentials.refresh(Request())
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    data = youtube.channels().list(part="id", mine=True).execute()
    channel_ids = {x.get("id") for x in data.get("items", [])}
    if channel["youtube_channel_id"] not in channel_ids:
        raise ValueError("Connected OAuth credential does not match selected YouTube channel")
    return youtube


def process_one() -> bool:
    job = claim_job()
    if job is None:
        return False
    with database() as conn:
        channel = conn.execute(
            """select * from autoclips_saas.channels
               where id=%s and org_id=%s and active=true""",
            (job["channel_id"], job["org_id"]),
        ).fetchone()
    if channel is None or not job["rights_confirmed"] or job["credit_state"] != "reserved":
        preflight_abort(job, ValueError("Channel or publication authorization missing"))
        return True

    # This file holds only the final MP4; the long original stays on the client's disk.
    with tempfile.TemporaryDirectory(prefix="autoclips-upload-") as directory:
        mp4 = str(Path(directory) / "final.mp4")
        try:
            storage_client().download_file(config("S3_BUCKET"), job["object_key"], mp4)
            metadata = verify_media(mp4, job["expected_sha256"], job["expected_bytes"])
            upload_path = normalize_media(mp4, metadata, directory)
            youtube = youtube_client(channel)
        except Exception as exc:
            preflight_abort(job, exc)
            return True
        try:
            media = MediaFileUpload(upload_path, mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
            request = youtube.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {"title": job["title"], "description": job["description"]},
                    "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
                },
                media_body=media,
                notifySubscribers=False,
            )
            # Any exception hereafter is AMBIGUOUS: YouTube might have accepted the upload.
            response = None
            while response is None:
                _, response = request.next_chunk()
            video_id = response.get("id")
            if not video_id:
                raise RuntimeError("YouTube did not return a video ID")
            confirm = youtube.videos().list(part="snippet,status", id=video_id).execute()
            matches = confirm.get("items", [])
            if (len(matches) != 1 or
                matches[0].get("snippet", {}).get("channelId") != channel["youtube_channel_id"] or
                matches[0].get("status", {}).get("privacyStatus") != "private"):
                raise RuntimeError("Uploaded video did not pass channel/private validation")
            with database() as conn:
                with conn.transaction():
                    capture_credit(conn, job["org_id"], job["id"], video_id)
            print("UPLOAD_CONFIRMED", str(job["id"]), video_id, flush=True)
        except Exception as exc:
            mark_uncertain(job, exc)
            print("UPLOAD_NEEDS_RECONCILIATION", str(job["id"]), type(exc).__name__, flush=True)
    return True


def reconcile(job_id: UUID, video_id: str):
    """Operator-only: verify that the video belongs to the OAuth channel, then capture.
    No retry or refund until reconciliation decides if upload succeeded.
    """
    with database() as conn:
        row = conn.execute(
            """select j.*,c.youtube_channel_id,c.token_ciphertext
               from autoclips_saas.jobs j join autoclips_saas.channels c on c.id=j.channel_id
               where j.id=%s and j.status='needs_reconciliation'""",
            (job_id,),
        ).fetchone()
    if not row:
        raise ValueError("Job not awaiting reconciliation")
    youtube = youtube_client(row)
    items = youtube.videos().list(part="snippet,status", id=video_id).execute().get("items", [])
    if len(items) != 1 or items[0].get("snippet", {}).get("channelId") != row["youtube_channel_id"]:
        raise ValueError("Unverified channel or video")
    if items[0].get("status", {}).get("privacyStatus") != "private":
        raise ValueError("Only private video can be reconciled")
    with database() as conn:
        with conn.transaction():
            capture_credit(conn, row["org_id"], row["id"], video_id)
    print("UPLOAD_RECONCILED", str(job_id), video_id, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reconcile", type=UUID, default=None)
    parser.add_argument("--video-id", default=None)
    args = parser.parse_args()
    if args.reconcile is not None:
        if not args.video_id:
            parser.error("--video-id is required with --reconcile")
        reconcile(args.reconcile, args.video_id)
    elif args.once:
        process_one()
    else:
        while True:
            if not process_one():
                time.sleep(5)
