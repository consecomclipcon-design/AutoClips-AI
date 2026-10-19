"""Streaming media upload endpoint; wrap in the application's bearer token gate."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from starlette.responses import JSONResponse

from .settings import home
from .media import MAX_SOURCE_BYTES, VALID_EXT


async def upload_media(request):
    raw = request.headers.get("x-filename", "")
    if not raw or len(raw) > 160 or "/" in raw or "\\" in raw or not re.fullmatch(r"[A-Za-z0-9._ -]+", raw):
        return JSONResponse({"error": "filename_invalid"}, status_code=400)
    extension = Path(raw).suffix.lower()
    if extension not in VALID_EXT:
        return JSONResponse({"error": "unsupported_video_extension"}, status_code=400)
    mimetype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mimetype not in {"video/mp4", "video/quicktime", "video/x-matroska", "video/webm", "application/octet-stream"}:
        return JSONResponse({"error": "unsupported_media_type"}, status_code=415)
    if request.headers.get("content-encoding"):
        return JSONResponse({"error": "encoded_upload_not_allowed"}, status_code=415)
    limit = min(MAX_SOURCE_BYTES, int(os.environ.get("AUTOCLIPS_MAX_UPLOAD_BYTES", str(MAX_SOURCE_BYTES))))
    length = request.headers.get("content-length")
    if length and (not length.isdecimal() or int(length) > limit):
        return JSONResponse({"error": "max_upload_size_exceeded", "limit_bytes": limit}, status_code=413)
    output = home() / "imports" / ("upload_" + secrets.token_hex(12) + extension)
    temp = output.with_suffix(output.suffix + ".part")
    digest = hashlib.sha256()
    count = 0
    try:
        with temp.open("xb") as stream:
            async for chunk in request.stream():
                count += len(chunk)
                if count > limit:
                    return JSONResponse({"error": "max_upload_size_exceeded", "limit_bytes": limit}, status_code=413)
                stream.write(chunk)
                digest.update(chunk)
        if not count:
            return JSONResponse({"error": "empty_upload"}, status_code=400)
        os.replace(temp, output)
        return JSONResponse({
            "filename": output.name,
            "bytes": count,
            "sha256": digest.hexdigest(),
            "next": "import_video(source=filename, source_kind='file', authorized=true)",
        }, status_code=201, headers={"cache-control":"no-store"})
    finally:
        temp.unlink(missing_ok=True)
