"""Durable archival of rendered source media to the private Railway S3 bucket.

Never remove a source unless an object HEAD confirms byte length and SHA-256.
A missing/broken S3 configuration disables cleanup instead of deleting files.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _config() -> dict | None:
    names = ("AUTOCLIPS_MEDIA_S3_ENDPOINT", "AUTOCLIPS_MEDIA_S3_BUCKET",
             "AUTOCLIPS_MEDIA_S3_ACCESS_KEY_ID", "AUTOCLIPS_MEDIA_S3_SECRET_ACCESS_KEY")
    values = {key: os.environ.get(key, "") for key in names}
    if any(not values[key] for key in names):
        return None
    if not values["AUTOCLIPS_MEDIA_S3_ENDPOINT"].startswith("https://"):
        return None
    return values


def configured() -> bool:
    return _config() is not None


def _client():
    config = _config()
    if not config:
        raise RuntimeError("Arquivo S3 não configurado; mídia local preservada")
    import boto3
    from botocore.config import Config
    client = boto3.client(
        "s3", endpoint_url=config["AUTOCLIPS_MEDIA_S3_ENDPOINT"],
        region_name=os.getenv("AUTOCLIPS_MEDIA_S3_REGION", "auto"),
        aws_access_key_id=config["AUTOCLIPS_MEDIA_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=config["AUTOCLIPS_MEDIA_S3_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"},
                      connect_timeout=15, read_timeout=120, retries={"max_attempts": 2}))
    return client, config["AUTOCLIPS_MEDIA_S3_BUCKET"]


def _object_key(project_id: str, local_path: Path) -> str:
    if not project_id.startswith("prj_") or not local_path.name.startswith("source"):
        raise ValueError("Nome de origem não elegível para arquivo")
    return f"sources/{project_id}/{local_path.name}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(2 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_source(project_id: str, path: Path) -> int:
    """Upload, verify and then unlink a completed, unused source. Returns freed bytes."""
    path = Path(path)
    if not configured() or not path.is_file() or path.is_symlink():
        return 0
    key = _object_key(project_id, path)
    length = path.stat().st_size
    checksum = _sha256(path)
    client, bucket = _client()
    client.upload_file(str(path), bucket, key, ExtraArgs={
        "ContentType": "video/mp4", "Metadata": {"sha256": checksum}})
    head = client.head_object(Bucket=bucket, Key=key)
    if (int(head.get("ContentLength", -1)) != length or
            head.get("Metadata", {}).get("sha256") != checksum):
        raise IOError("O arquivo S3 não passou na validação SHA-256/tamanho")
    # Do not delete a file replaced during the upload.
    if not path.is_file() or path.stat().st_size != length or _sha256(path) != checksum:
        raise IOError("Origem local foi alterada durante o arquivamento")
    path.unlink()
    print("AUTOCLIPS_SOURCE_ARCHIVED", project_id, "freed_bytes", length, flush=True)
    return length


def restore_source(project_id: str, path: Path) -> Path:
    """Restore a missing source for an explicitly requested re-render."""
    path = Path(path)
    if path.is_file():
        return path
    key = _object_key(project_id, path)
    client, bucket = _client()
    head = client.head_object(Bucket=bucket, Key=key)
    expected = head.get("Metadata", {}).get("sha256")
    length = int(head.get("ContentLength", -1))
    if not expected or length < 16:
        raise IOError("Fonte arquivada não contém metadados de integridade")
    import shutil
    if shutil.disk_usage(path.parent).free < length + 95 * 1024 * 1024:
        raise IOError("Espaço insuficiente para restaurar a fonte; libere espaço antes de reeditar")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".restore.part")
    try:
        client.download_file(bucket, key, str(partial))
        if partial.stat().st_size != length or _sha256(partial) != expected:
            raise IOError("Falha na conferência da mídia restaurada")
        os.replace(partial, path)
        return path
    finally:
        partial.unlink(missing_ok=True)
