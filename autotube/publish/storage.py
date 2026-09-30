"""인스타그램용 공개 URL 호스팅 — S3 호환 스토리지(Cloudflare R2 등). 선택 기능.

필요: pip install boto3 + 환경변수 S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_PUBLIC_BASE_URL
"""
from __future__ import annotations

from pathlib import Path

from autotube.config import env


def upload_public(path: Path, key: str) -> str:
    import boto3  # 선택 의존성

    s3 = boto3.client(
        "s3",
        endpoint_url=env("S3_ENDPOINT"),
        aws_access_key_id=env("S3_ACCESS_KEY"),
        aws_secret_access_key=env("S3_SECRET_KEY"),
    )
    s3.upload_file(str(path), env("S3_BUCKET"), key, ExtraArgs={"ContentType": "video/mp4"})
    return f"{env('S3_PUBLIC_BASE_URL').rstrip('/')}/{key}"
