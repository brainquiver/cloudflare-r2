---
type: Repository Guide
title: Cloudflare R2
description: Dependency-free Python tools to list, upload, download and delete Cloudflare R2 objects.
status: stable
tags: [data, r2, storage]
generated:
  by: claude-code/opus-5.5
  at: 2026-09-29T18:00:00Z
supervised:
  by: human:ciprian-florin_ifrim
  at: 2026-09-29T18:00:00Z
edited:
  by: claude-code/opus-5.5
  at: 2026-10-02T18:04:52Z
---

# Cloudflare R2

Two Python tools use Cloudflare R2 through its S3 API, and they make their SigV4 signatures by hand. They need only the standard library, so they run on any machine with Python 3.10 or later.

An upload streams its body from disk, and the signature uses the digest from a first pass. A 500 MB shard therefore stays on disk for the whole upload.

| What | Where |
|---|---|
| List buckets and objects, download, delete | `r2.py` |
| Upload files and shard sets | `push.py` |

**Each command can run again safely, because an upload and a download both skip what is already complete.**

## 1. Build and Run

    python3 r2.py buckets
    python3 r2.py ls BUCKET [--prefix P]
    python3 r2.py get BUCKET --prefix P --out DIR
    python3 r2.py get BUCKET --key K --out PATH
    python3 r2.py rm BUCKET --prefix P --yes
    python3 push.py BUCKET FILE... [--prefix P]
    python3 push.py BUCKET --shard-set DIR [--prefix P]

The tools run from the source, without a build or a package install.

### 1.1 Credentials

| Variable | Value |
|---|---|
| `R2_ENDPOINT` | the account endpoint |
| `R2_ACCESS_KEY_ID` | the access key |
| `R2_SECRET_ACCESS_KEY` | the secret key |

Both tools read these variables from the file that `--env FILE` names, which is `.env` in the working directory by default. If the file is absent, they read the variables from the environment. A variable that is still absent stops the tool, and the message names it.

## 2. Directory Tree

    r2.py      signatures, lists, downloads and deletes
    push.py    uploads, retries and the shard set check

## 3. Concepts

**A prefix matches the start of a key.** R2 stores its keys in one flat list, so `ls --prefix general-32k` matches every key that starts with those characters, and `rm --prefix` deletes each of them.

**A PUT is atomic.** A broken upload leaves the bucket as it was before the PUT, so a retry is safe without a cleanup step.

## 4. Rules

**A delete needs `--yes`.** The tool prints the count and the size first, because a prefix that matches too much is the one mistake that it cannot undo.

**Never pass a credential as an argument, and never log one.** An argument reaches the process list and the shell history.

## 5. Uploads

| Behaviour | Reason |
|---|---|
| `push.py` lists the bucket first, and skips a key whose size already matches | A large transfer on a slow uplink needs several attempts, and a restart must send only what is still absent |
| A failed PUT is tried again up to 6 times, and each pause is 5 seconds longer than the last | A short network fault must not stop a long upload |
| Each new try signs the request again | The signature carries a timestamp, so an old signature fails |
| `push.py` creates the bucket when it does not exist | An upload to a new bucket then needs one command |

## 6. Shard Sets

`--shard-set DIR` sends a directory that holds shards and a `manifest.json`. The tool checks every shard before it sends anything.

| Step | Check |
|---|---|
| 1 | Each shard that the manifest names must exist, at the size in `compressed_bytes` |
| 2 | Each shard must match its BLAKE2b digest in the manifest |
| 3 | The shards go first |
| 4 | The manifest goes last |

**Send the manifest after its shards.** An interrupted run then leaves shards without a manifest, and a reader cannot take the set for a complete one.

## 7. Downloads

| Behaviour | Reason |
|---|---|
| `get` writes each key under `--out` | A prefix keeps its own shape on disk |
| Each object streams to a `.part` file, and the file takes its name when it is complete | An interrupted download leaves a `.part` file, and only a complete file takes the final name |
| A file that already exists at the same size is skipped | An interrupted run continues with the next object, and a complete file is not fetched again |

## 8. Outputs

| Command | Output |
|---|---|
| `ls` | one line for each object with its size, then the count and the total |
| `get` | one line for each object, then the counts of fetched and skipped objects and the total size |
| `push.py` | one line for each object with its size and the HTTP status, then the counts of sent and skipped objects |
| `rm` | the count and the size, then one line for each deleted object |

## 9. Limitations

| Limitation | Reason |
|---|---|
| One PUT for each object, without multipart upload | A single PUT carries up to 5 GB |
| An interrupted download fetches that object again from the start | The tool fetches the `.part` file again in full, from the first byte |
| Buckets are deleted by hand | `push.py` creates a bucket when it needs one, and a bucket deletion is rare |
| The region is always `auto` | R2 signs every request as `auto` |
