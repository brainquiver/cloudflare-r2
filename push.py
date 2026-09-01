"""Upload to R2, skip what is already there and retry what breaks.

On a slow or saturated uplink, a large PUT breaks often enough that a long
transfer needs several attempts, and a restart must send only what is still
absent.

The tool lists the bucket first and skips each key whose size already matches.
It retries a failed PUT, and each pause is longer than the one before. A PUT is
atomic, so a broken one leaves the bucket as it was before the PUT.
"""
import argparse, hashlib, os, pathlib, sys, time
import urllib.error, urllib.parse, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from r2 import DEFAULT_ENV, load_env, sign, objects  # noqa: E402

TRIES = 6


def put(bucket, key, path):
    size = path.stat().st_size
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    url, headers = sign("PUT", f"/{bucket}/{urllib.parse.quote(key, safe='/')}",
                        h.hexdigest(), length=size)
    headers["content-type"] = "application/octet-stream"
    for attempt in range(1, TRIES + 1):
        try:
            with open(path, "rb") as body:
                r = urllib.request.urlopen(
                    urllib.request.Request(url, data=body, method="PUT", headers=headers),
                    timeout=1800)
            return r.status
        except Exception as e:
            if attempt == TRIES:
                raise
            pause = 5 * attempt
            print(f"    {type(e).__name__} on try {attempt}, next try in {pause}s",
                  flush=True)
            time.sleep(pause)
            # The signature carries a timestamp, so a retry needs a fresh one.
            url, headers = sign("PUT", f"/{bucket}/{urllib.parse.quote(key, safe='/')}",
                                h.hexdigest(), length=size)
            headers["content-type"] = "application/octet-stream"


def make_bucket(bucket):
    """Create the bucket with a PUT on its name.

    A bucket that this account already owns is accepted.
    """
    empty = hashlib.sha256(b"").hexdigest()
    url, headers = sign("PUT", "/" + bucket, empty, length=0)
    try:
        urllib.request.urlopen(
            urllib.request.Request(url, data=b"", method="PUT", headers=headers),
            timeout=120)
        print(f"  bucket {bucket} created", flush=True)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if 409 == e.code or "BucketAlreadyOwnedByYou" in body:
            return
        raise


def send(bucket, prefix, files):
    make_bucket(bucket)
    have = {k: s for k, s in objects(bucket, prefix)}
    sent = skipped = 0
    for f in files:
        key = f"{prefix}/{f.name}" if prefix else f.name
        if have.get(key) == f.stat().st_size:
            skipped += 1
            continue
        status = put(bucket, key, f)
        sent += 1
        print(f"  {key}  {f.stat().st_size/1e6:8.1f} MB  HTTP {status}", flush=True)
    print(f"  {bucket}/{prefix}: {sent} sent, {skipped} already there", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bucket")
    parser.add_argument("files", nargs="+", type=pathlib.Path)
    parser.add_argument("--prefix", default="",
                        help="a key prefix, so the objects land under one name")
    parser.add_argument("--env", default=DEFAULT_ENV)
    a = parser.parse_args()
    load_env(a.env)
    for want in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        if not os.environ.get(want):
            sys.exit(f"{want} is not set, so the .env did not load")
    missing = [f for f in a.files if not f.is_file()]
    if missing:
        sys.exit(f"not a file: {missing[0]}")
    send(a.bucket, a.prefix, a.files)


if __name__ == "__main__":
    main()
