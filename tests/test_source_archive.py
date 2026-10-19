"""Storage regression tests: never discard unverified source files."""
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

from autoclips import source_archive


class MemoryS3:
    def __init__(self, broken=False):
        self.items = {}
        self.broken = broken

    def upload_file(self, local, bucket, key, ExtraArgs):
        self.items[(bucket, key)] = (Path(local).read_bytes(), ExtraArgs["Metadata"])

    def head_object(self, Bucket, Key):
        blob, metadata = self.items[(Bucket, Key)]
        if self.broken:
            metadata = {"sha256": "bad"}
        return {"ContentLength": len(blob), "Metadata": metadata}

    def download_file(self, bucket, key, local):
        Path(local).write_bytes(self.items[(bucket, key)][0])


@pytest.fixture
def archived(tmp_path, monkeypatch):
    for name in ("AUTOCLIPS_MEDIA_S3_ENDPOINT", "AUTOCLIPS_MEDIA_S3_BUCKET",
                 "AUTOCLIPS_MEDIA_S3_ACCESS_KEY_ID", "AUTOCLIPS_MEDIA_S3_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "https://storage.example" if name.endswith("ENDPOINT") else "test")
    bucket = "private-bucket"
    store = MemoryS3()
    monkeypatch.setattr(source_archive, "_client", lambda: (store, bucket))
    folder = tmp_path / "projects" / "prj_test123"
    folder.mkdir(parents=True)
    path = folder / "source.mp4"
    path.write_bytes(b"real-original-file-data" * 400)
    return folder, path, store


def test_archived_source_is_verified_and_can_be_restored(archived, monkeypatch):
    folder, path, store = archived
    from shutil import disk_usage
    monkeypatch.setattr("shutil.disk_usage",
                        lambda _: SimpleNamespace(free=300 * 1024 * 1024))
    data = path.read_bytes()
    freed = source_archive.archive_source("prj_test123", path)
    assert freed == len(data)
    assert not path.exists()
    restored = source_archive.restore_source("prj_test123", path)
    assert restored.read_bytes() == data
    assert source_archive.archive_source("prj_test123", path) == freed


def test_failed_object_verification_never_deletes_original(archived, monkeypatch):
    folder, path, store = archived
    store.broken = True
    with pytest.raises(IOError, match="SHA-256"):
        source_archive.archive_source("prj_test123", path)
    assert path.is_file()


def test_no_bucket_credentials_leaves_local_media_untouched(archived, monkeypatch):
    folder, path, store = archived
    monkeypatch.delenv("AUTOCLIPS_MEDIA_S3_SECRET_ACCESS_KEY")
    assert source_archive.archive_source("prj_test123", path) == 0
    assert path.exists()
