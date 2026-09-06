"""List, download and delete R2 objects, with SigV4 signed by hand.

    python3 r2.py buckets
    python3 r2.py ls BUCKET [--prefix P]
    python3 r2.py get BUCKET --prefix P --out DIR
    python3 r2.py get BUCKET --key K --out PATH
    python3 r2.py rm BUCKET --prefix P --yes

LIST needs a canonical query string, so the signer here takes query parameters.
An upload signs an empty one. The rest of the signature is the same.

A delete needs --yes, because a prefix that matches more than intended is the
one mistake that this tool cannot undo.

A get writes the key under --out, and a prefix keeps its own folder structure.
It streams each object to disk, because an object can be a checkpoint of several
gigabytes. It skips a file that is already there at the same size, so a second
run fetches only the files that are still absent.
"""
import argparse, datetime, hashlib, hmac, os, pathlib, sys
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

# The credentials file, relative to the working directory. Git ignores it, and
# the tools keep its values out of the output, the logs and the manifests.
DEFAULT_ENV = ".env"


def load_env(path):
    """Read the .env, and keep every value out of the output.

    CONTRACT: an absent file is acceptable when the environment already holds the
    credentials. A machine can set them in its environment without a .env file,
    and an error here would stop the tool on that machine. The caller checks the
    three variables afterwards, so an environment without them still fails, and
    the message names the absent variable.
    """
    if not pathlib.Path(path).exists():
        return
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def sign(method, path, payload_hash, query=None, length=None):
    ep = os.environ["R2_ENDPOINT"].rstrip("/")
    ak, sk = os.environ["R2_ACCESS_KEY_ID"], os.environ["R2_SECRET_ACCESS_KEY"]
    host = ep.split("//", 1)[1]
    now = datetime.datetime.now(datetime.timezone.utc)
    amz, ds = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz}
    names = ";".join(sorted(headers))
    canon_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    # The canonical query string is sorted by key and each part is encoded.
    q = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
                 for k, v in sorted((query or {}).items()))
    canon = f"{method}\n{path}\n{q}\n{canon_headers}\n{names}\n{payload_hash}"
    scope = f"{ds}/auto/s3/aws4_request"
    sts = f"AWS4-HMAC-SHA256\n{amz}\n{scope}\n{hashlib.sha256(canon.encode()).hexdigest()}"
    step = lambda k, m: hmac.new(k, m.encode(), hashlib.sha256).digest()
    key = step(step(step(step(("AWS4" + sk).encode(), ds), "auto"), "s3"), "aws4_request")
    sig = hmac.new(key, sts.encode(), hashlib.sha256).hexdigest()
    out = dict(headers)
    out["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={ak}/{scope}, "
                            f"SignedHeaders={names}, Signature={sig}")
    if length is not None:
        out["Content-Length"] = str(length)
    return ep + path + (f"?{q}" if q else ""), out


def call(method, path, query=None, expect=(200, 204)):
    empty = hashlib.sha256(b"").hexdigest()
    url, headers = sign(method, path, empty, query=query)
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, method=method, headers=headers), timeout=300)
        return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} failed: {e.code} {e.read().decode(errors='replace')[:300]}")


def buckets():
    root = ET.fromstring(call("GET", "/"))
    rows = [(b.findtext(NS + "Name"), b.findtext(NS + "CreationDate", "")[:10])
            for b in root.iter(NS + "Bucket")]
    if not rows:
        print("this account does not have any buckets")
        return
    w = max(len(n) for n, _ in rows)
    for name, made in rows:
        print(f"  {name.ljust(w)}  created {made}")


def objects(bucket, prefix=""):
    """Every key under the prefix, read through each continuation token to the end."""
    out, token = [], None
    while True:
        q = {"list-type": "2", "max-keys": "1000"}
        if prefix:
            q["prefix"] = prefix
        if token:
            q["continuation-token"] = token
        root = ET.fromstring(call("GET", f"/{bucket}", query=q))
        for c in root.iter(NS + "Contents"):
            out.append((c.findtext(NS + "Key"), int(c.findtext(NS + "Size", "0"))))
        if root.findtext(NS + "IsTruncated") == "true":
            token = root.findtext(NS + "NextContinuationToken")
        else:
            return out


def download(bucket, key, out):
    """Stream one object to a path, and return the number of bytes written.

    CONTRACT: stream it. call() reads a whole response into memory, which suits a
    listing, and an object can be a checkpoint of several gigabytes.
    """
    empty = hashlib.sha256(b"").hexdigest()
    url, headers = sign("GET", f"/{bucket}/{urllib.parse.quote(key, safe='/')}", empty)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(out.suffix + ".part")
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, method="GET", headers=headers),
                timeout=300) as r, open(part, "wb") as f:
            written = 0
            for chunk in iter(lambda: r.read(1 << 22), b""):
                f.write(chunk)
                written += len(chunk)
    except urllib.error.HTTPError as e:
        part.unlink(missing_ok=True)
        sys.exit(f"GET {key} failed: {e.code} {e.read().decode(errors='replace')[:300]}")
    # CAUTION: rename only when the body is complete. An interrupted get then leaves
    # a .part file, and the size check accepts only a complete file.
    part.replace(out)
    return written


def get(bucket, prefix, key, out):
    """Fetch one key, or every key under a prefix, under out."""
    if key:
        target = out / key.rsplit("/", 1)[-1] if out.is_dir() else out
        if target.exists() and target.stat().st_size:
            print(f"  {target} already {target.stat().st_size:,} bytes, skipped")
            return
        n = download(bucket, key, target)
        print(f"  {key} -> {target}  {n:,} bytes")
        return
    found = objects(bucket, prefix)
    if not found:
        sys.exit(f"nothing under {prefix!r} in {bucket}")
    done = skipped = total = 0
    for k, size in found:
        target = out / k
        if target.exists() and target.stat().st_size == size:
            skipped += 1
            continue
        total += download(bucket, k, target)
        done += 1
    print(f"  {done} fetched, {skipped} already there, {total/1e6:.1f} MB into {out}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["buckets", "ls", "get", "rm"])
    p.add_argument("bucket", nargs="?")
    p.add_argument("--prefix", default="")
    p.add_argument("--key", default="", help="one object, in place of a prefix")
    p.add_argument("--out", type=pathlib.Path, help="where a get writes")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--env", default=DEFAULT_ENV)
    a = p.parse_args()
    load_env(a.env)
    for want in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        if not os.environ.get(want):
            sys.exit(f"{want} is not set, so the .env did not load")

    if a.action == "buckets":
        return buckets()
    if not a.bucket:
        sys.exit("that action needs a bucket")
    if a.action == "get":
        if not a.out:
            sys.exit("a get needs --out, a directory for a prefix or a path for a key")
        return get(a.bucket, a.prefix, a.key, a.out)
    found = objects(a.bucket, a.prefix)
    total = sum(s for _, s in found)
    if a.action == "ls":
        for k, s in found:
            print(f"  {s/1e6:10.1f} MB  {k}")
        print(f"  {len(found)} objects, {total/1e9:.2f} GB")
        return
    if not found:
        print("0 objects match, so there is nothing to delete")
        return
    print(f"{len(found)} objects, {total/1e9:.2f} GB, under {a.bucket}/{a.prefix or '(all)'}")
    if not a.yes:
        sys.exit("a delete needs --yes")
    for i, (k, _) in enumerate(found, 1):
        call("DELETE", f"/{a.bucket}/{urllib.parse.quote(k, safe='/')}")
        print(f"  deleted {i}/{len(found)}  {k}", flush=True)


if __name__ == "__main__":
    main()
