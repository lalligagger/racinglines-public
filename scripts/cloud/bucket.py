"""
The data bucket from a cloud session (no gcloud there): Google Cloud Storage's S3-compatible API
with an HMAC key. See docs/data.md#data-bucket.

    python scripts/cloud/bucket.py pull             # data folders + the database dump -> local
    python scripts/cloud/bucket.py push PREFIX PATH # upload a folder (e.g. results/<session> data/runs/…)
    python scripts/cloud/bucket.py ls [PREFIX]

Environment: RACINGLINES_GCS_BUCKET, RACINGLINES_GCS_HMAC_ID, RACINGLINES_GCS_HMAC_SECRET.
Needs boto3 (installed on demand). The network must allow storage.googleapis.com.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://storage.googleapis.com"
# bucket prefix -> local folder; the same list as scripts/cloud/bucket.sh
FOLDERS = {
    "live": "data/runs/live",
    "runs/f1": "data/runs/f1",
    "raw/mtb_dh": "data/raw/mtb_dh",
    "archive/markets": "data/archive/markets",
    "db": "data/archive/bucket-db",
}


def client():
    try:
        import boto3
    except ImportError:
        import shutil
        if shutil.which("uv"):                     # start.sh's venv is built by uv and has no pip
            subprocess.run(["uv", "pip", "install", "-q", "--python", sys.executable, "boto3"], check=True)
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "boto3"], check=True)
        import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name="auto",
                        aws_access_key_id=os.environ["RACINGLINES_GCS_HMAC_ID"],
                        aws_secret_access_key=os.environ["RACINGLINES_GCS_HMAC_SECRET"],
                        # GCS rejects boto3's default upload checksums (SignatureDoesNotMatch on put)
                        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                      request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required"))


def keys(s3, bucket, prefix):
    token = None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        for o in page.get("Contents", []):
            yield o["Key"], o["Size"]
        if not page.get("IsTruncated"):
            return
        token = page["NextContinuationToken"]


def pull(s3, bucket):
    for prefix, local in FOLDERS.items():
        n = size = 0
        for key, sz in keys(s3, bucket, prefix + "/"):
            dest = ROOT / local / key[len(prefix) + 1:]
            if dest.exists() and dest.stat().st_size == sz:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(dest))
            n, size = n + 1, size + sz
        print(f"{prefix}/ -> {local}: {n} files, {size / 1e6:.1f} MB new")


def push(s3, bucket, prefix, path):
    base = ROOT / path
    files = [p for p in base.rglob("*") if p.is_file()] if base.is_dir() else [base]
    for p in files:
        rel = p.relative_to(base).as_posix() if base.is_dir() else p.name
        s3.upload_file(str(p), bucket, f"{prefix.rstrip('/')}/{rel}")
    print(f"{path} -> gs://{bucket}/{prefix}: {len(files)} files")


def main(argv):
    bucket = os.environ["RACINGLINES_GCS_BUCKET"]
    s3 = client()
    cmd = argv[0] if argv else ""
    if cmd == "pull":
        pull(s3, bucket)
    elif cmd == "push" and len(argv) == 3:
        push(s3, bucket, argv[1], argv[2])
    elif cmd == "ls":
        for key, sz in keys(s3, bucket, argv[1] if len(argv) > 1 else ""):
            print(f"{sz:>12,}  {key}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
