"""Shared fixtures: the fake service, the credentials and a frozen clock.

Every test runs inside its own temporary directory, so the tools never read a real .env.
Every test also runs behind the fake transport, so no test can reach the network. Pauses
between retries take no time, which keeps the retry tests fast.
"""
import datetime
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import push  # noqa: E402
import s3  # noqa: E402
from fake_service import Transport  # noqa: E402

# The example credentials that AWS publishes for documentation. They sign nothing real.
ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
B2_ENDPOINT = "https://s3.eu-central-003.backblazeb2.com"
CLOUDFLARE_ENDPOINT = "https://0123456789abcdef.r2.cloudflarestorage.com"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Run in a temporary directory, with a fake transport and pauses that take no time."""
    monkeypatch.chdir(tmp_path)
    transport = Transport()
    monkeypatch.setattr("urllib.request.urlopen", transport)
    monkeypatch.setattr(push.time, "sleep", lambda seconds: None)
    return transport


@pytest.fixture
def transport(isolated):
    return isolated


@pytest.fixture
def credentials(monkeypatch):
    """Give the tools a B2 endpoint, with no region set."""
    monkeypatch.setenv("S3_ENDPOINT", B2_ENDPOINT)
    monkeypatch.setenv("S3_ACCESS_KEY_ID", ACCESS_KEY)
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", SECRET_KEY)
    monkeypatch.delenv("S3_REGION", raising=False)


class _FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Sign every request at 2026-10-20T12:00:00Z."""
    fake = types.SimpleNamespace(datetime=_FrozenDatetime, timezone=datetime.timezone)
    monkeypatch.setattr(s3, "datetime", fake)
