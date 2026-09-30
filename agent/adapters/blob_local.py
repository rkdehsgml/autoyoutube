"""LocalBlobStore — R2 대신 로컬 폴더에 같은 키 구조(jobs/{job_id}/...)로 저장한다."""
from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath


class LocalBlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = PurePosixPath(key)
        if not key or p.is_absolute() or ".." in p.parts:
            raise ValueError(f"잘못된 키: {key!r}")
        return self.root.joinpath(*p.parts)

    def put(self, key: str, src: Path | bytes, content_type: str) -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src, (bytes, bytearray)):
            dest.write_bytes(bytes(src))
        else:
            shutil.copyfile(src, dest)
        return key

    def get(self, key: str, dest: Path) -> Path:
        src = self._path(key)
        if not src.exists():
            raise FileNotFoundError(key)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return dest

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def presigned_get(self, key: str, expires: int = 3600) -> str:
        return self._path(key).as_uri()

    def local_path(self, key: str) -> Path:
        return self._path(key)
