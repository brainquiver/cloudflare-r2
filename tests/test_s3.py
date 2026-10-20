"""Request signing: each signature must equal the one that AWS's own signer makes."""
import hashlib

import s3
from conftest import CLOUDFLARE_ENDPOINT

EMPTY = hashlib.sha256(b"").hexdigest()
LIST = {"list-type": "2", "max-keys": "1000", "prefix": "reason-qa-geology-finetune/"}
SHARD = "/datasets/classify-typed/curated/default/train-00000-of-00001.parquet"

# CONTRACT: botocore 1.43.69 made each expected signature on 2026-10-20 with S3SigV4Auth, from
# the credentials in conftest.py and a clock frozen at 2026-10-20T12:00:00Z. A different value
# means that the signer no longer signs in the way that S3 checks a signature.
CLOUDFLARE_LIST = "3f43c3e128c004ed1854ca223703a8b46963a090c4f8811824b85b9f1a934153"
B2_LIST = "9245997b51caf4ccd5642e281ebb8e04b29cfb52287b0f2d8a061e8a78625242"
B2_PUT_WITH_HASH = "993eab84b6e50d4c2883aa07b99aabb432bff85399516b3a150c5d8f28f2fa94"


def signature_of(headers):
    return headers["Authorization"].split("Signature=")[1]


def signed_names(headers):
    return headers["Authorization"].split("SignedHeaders=")[1].split(",")[0]


def test_signature_matches_aws_for_r2_with_no_region(credentials, frozen_clock, monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", CLOUDFLARE_ENDPOINT)
    _, headers = s3.sign("GET", "/datasets", EMPTY, query=LIST)
    assert "/20261020/auto/s3/aws4_request" in headers["Authorization"]
    assert signature_of(headers) == CLOUDFLARE_LIST


def test_signature_matches_aws_for_the_b2_region(credentials, frozen_clock, monkeypatch):
    monkeypatch.setenv("S3_REGION", "eu-central-003")
    _, headers = s3.sign("GET", "/datasets", EMPTY, query=LIST)
    assert "/20261020/eu-central-003/s3/aws4_request" in headers["Authorization"]
    assert signature_of(headers) == B2_LIST


def test_signature_covers_the_hash_metadata_header(credentials, frozen_clock, monkeypatch):
    monkeypatch.setenv("S3_REGION", "eu-central-003")
    digest = hashlib.sha256(b"hello").hexdigest()
    _, headers = s3.sign("PUT", SHARD, digest, extra_headers={"x-amz-meta-sha256": digest})
    assert signed_names(headers) == "host;x-amz-content-sha256;x-amz-date;x-amz-meta-sha256"
    assert headers["x-amz-meta-sha256"] == digest
    assert signature_of(headers) == B2_PUT_WITH_HASH
