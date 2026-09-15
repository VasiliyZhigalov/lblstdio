from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

from app.application.ports.storage.file_storage import IFileStorage


class LocalFileStorage(IFileStorage):
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, filename: str) -> str:
        name = Path(filename).name
        if not name or name in {".", ".."}:
            raise ValueError("invalid filename")
        return name

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"path escapes storage root: {relative_path}")
        return candidate

    async def save(self, relative_dir: str, filename: str, data: bytes) -> str:
        name = self._safe_name(filename)
        directory = self._resolve(relative_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = (directory / name).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError(f"path escapes storage root: {filename}")
        if target.exists():
            target = directory / f"{target.stem}_{uuid4().hex[:8]}{target.suffix}"
            target = target.resolve()
        await asyncio.to_thread(target.write_bytes, data)
        return target.relative_to(self._root).as_posix()

    async def read(self, relative_path: str) -> bytes:
        path = self._resolve(relative_path)
        return await asyncio.to_thread(path.read_bytes)

    def get_absolute_path(self, relative_path: str) -> str:
        return str(self._resolve(relative_path))

    async def delete(self, relative_path: str) -> None:
        path = self._resolve(relative_path)
        if path.is_file():
            await asyncio.to_thread(path.unlink)

    async def delete_directory(self, relative_dir: str) -> None:
        path = self._resolve(relative_dir)
        if path.exists() and path.is_dir():
            await asyncio.to_thread(shutil.rmtree, path)

    async def list_files(self, relative_dir: str) -> dict[str, bytes]:
        root = self._resolve(relative_dir)
        if not root.exists() or not root.is_dir():
            return {}

        def _walk() -> dict[str, bytes]:
            entries: dict[str, bytes] = {}
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                entries[rel] = path.read_bytes()
            return entries

        return await asyncio.to_thread(_walk)
