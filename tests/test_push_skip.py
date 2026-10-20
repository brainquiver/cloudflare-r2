"""Skip decisions: an upload skips a file only when its size and its stored hash both match.

A size match alone misses a file that an edit left at the same byte count. Each upload now
stores the SHA-256 of the file as object metadata, and a later run compares that hash.
"""
import hashlib
import sys

import push
from fake_service import Reply, error, listing


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["push.py", *args])
    push.main()


def bucket_exists(transport):
    transport.on("PUT", "/b", error(409, "BucketAlreadyOwnedByYou"))


def test_an_upload_stores_the_hash_as_signed_metadata(transport, credentials, tmp_path):
    f = tmp_path / "a.parquet"
    f.write_bytes(b"abc")
    transport.on("PUT", "/b/a.parquet", Reply(200))
    push.put("b", "a.parquet", f)
    sent = transport.find("PUT", "/b/a.parquet")[-1]
    assert sent.headers["x-amz-meta-sha256"] == sha(b"abc")
    assert "x-amz-meta-sha256" in sent.headers["authorization"].split("SignedHeaders=")[1]


def test_a_same_size_file_with_another_hash_is_sent_again(
        transport, credentials, tmp_path, monkeypatch):
    f = tmp_path / "a.parquet"
    f.write_bytes(b"abc")
    bucket_exists(transport)
    transport.on("GET", "/b", listing([("a.parquet", 3)]), query={"list-type"})
    transport.on("HEAD", "/b/a.parquet", Reply(200, headers={"x-amz-meta-sha256": sha(b"xyz")}))
    transport.on("PUT", "/b/a.parquet", Reply(200))
    run(monkeypatch, "b", str(f))
    assert len(transport.find("PUT", "/b/a.parquet")) == 1


def test_a_file_with_the_same_size_and_hash_is_skipped(
        transport, credentials, tmp_path, monkeypatch):
    f = tmp_path / "a.parquet"
    f.write_bytes(b"abc")
    bucket_exists(transport)
    transport.on("GET", "/b", listing([("a.parquet", 3)]), query={"list-type"})
    transport.on("HEAD", "/b/a.parquet", Reply(200, headers={"x-amz-meta-sha256": sha(b"abc")}))
    run(monkeypatch, "b", str(f))
    assert transport.find("PUT", "/b/a.parquet") == []


def test_an_object_without_a_hash_is_skipped_on_size_and_reported(
        transport, credentials, tmp_path, monkeypatch, capsys):
    # An object from an older version of the tool carries no hash. A new upload of every such
    # file costs a full transfer, so the object keeps the size check, and the run reports it.
    f = tmp_path / "a.parquet"
    f.write_bytes(b"abc")
    bucket_exists(transport)
    transport.on("GET", "/b", listing([("a.parquet", 3)]), query={"list-type"})
    transport.on("HEAD", "/b/a.parquet", Reply(200))
    run(monkeypatch, "b", str(f))
    assert transport.find("PUT", "/b/a.parquet") == []
    assert "1 matched on size only" in capsys.readouterr().out


def test_a_file_that_the_bucket_lacks_is_sent(transport, credentials, tmp_path, monkeypatch):
    f = tmp_path / "a.parquet"
    f.write_bytes(b"abc")
    bucket_exists(transport)
    transport.on("GET", "/b", listing([]), query={"list-type"})
    transport.on("PUT", "/b/a.parquet", Reply(200))
    run(monkeypatch, "b", str(f))
    assert len(transport.find("PUT", "/b/a.parquet")) == 1
