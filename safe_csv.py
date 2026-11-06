"""Escritura CSV con bloqueo y reemplazo atómico.

`products.csv` se reescribe entero mediante un fichero temporal y `os.replace`.
`conversation_log.csv` solo se abre en modo append: no hay una función que lo trunque.
"""

from __future__ import annotations

import csv
import fcntl
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

LOG_FIELDS = ("actor", "message", "tool_call", "timestamp")
PRODUCT_FIELDS = ("id", "name", "quantity", "unit")


@contextmanager
def file_lock(path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_rows(path: Path, fieldnames: tuple[str, ...]) -> list[dict[str, str]]:
    path = Path(path)
    with file_lock(path):
        return _read_unlocked(path, fieldnames)


def _read_unlocked(path: Path, fieldnames: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw in reader:
            if raw is None:
                continue
            if all(not (value or "").strip() for value in raw.values()):
                continue
            rows.append({key: (raw.get(key) or "").strip() for key in fieldnames})
        return rows


def replace_rows(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path = Path(path)
    with file_lock(path):
        _replace_unlocked(path, fieldnames, rows)


def _replace_unlocked(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({key: "" if row.get(key) is None else str(row.get(key)) for key in fieldnames})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def append_row(path: Path, fieldnames: tuple[str, ...], row: dict[str, str]) -> None:
    """Añade una fila. El fichero se abre en modo append y no se reescribe."""
    path = Path(path)
    with file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        needs_header = (not path.exists()) or path.stat().st_size == 0
        needs_leading_newline = False
        if not needs_header:
            with open(path, "rb") as existing:
                existing.seek(-1, os.SEEK_END)
                needs_leading_newline = existing.read(1) != b"\n"
        with open(path, "a", newline="", encoding="utf-8") as handle:
            if needs_leading_newline:
                handle.write("\n")
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                lineterminator="\n",
                extrasaction="ignore",
            )
            if needs_header:
                writer.writeheader()
            writer.writerow({key: "" if row.get(key) is None else str(row.get(key)) for key in fieldnames})
            handle.flush()
            os.fsync(handle.fileno())


def apply_rows(
    path: Path,
    fieldnames: tuple[str, ...],
    mutator: Callable[[list[dict[str, str]]], tuple[list[dict[str, str]], bool]],
) -> list[dict[str, str]]:
    """Lee y, si el mutador lo pide, reescribe bajo el mismo bloqueo."""
    path = Path(path)
    with file_lock(path):
        rows = _read_unlocked(path, fieldnames)
        updated, should_write = mutator(rows)
        if should_write:
            _replace_unlocked(path, fieldnames, updated)
        return updated
