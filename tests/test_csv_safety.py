from __future__ import annotations

import threading

import pytest

from safe_csv import LOG_FIELDS, PRODUCT_FIELDS, append_row, apply_rows, read_rows, replace_rows
import safe_csv


def test_append_keeps_previous_rows_and_quotes_special_characters(tmp_path):
    path = tmp_path / "conversation_log.csv"
    first = {
        "actor": "user",
        "message": 'dijo "hola", y siguió',
        "tool_call": "",
        "timestamp": "2026-11-06T08:00:00+00:00",
    }
    second = {
        "actor": "tool",
        "message": "línea 1\nlínea 2",
        "tool_call": "list_inventory",
        "timestamp": "2026-11-06T08:00:01+00:00",
    }
    append_row(path, LOG_FIELDS, first)
    snapshot = path.read_bytes()
    append_row(path, LOG_FIELDS, second)
    updated = path.read_bytes()
    assert updated.startswith(snapshot)
    rows = read_rows(path, LOG_FIELDS)
    assert rows == [first, second]
    text = path.read_text(encoding="utf-8")
    assert text.count("actor,message,tool_call,timestamp") == 1
    assert '""hola""' in text or '"dijo ""hola""' in text


def test_append_repairs_a_header_without_newline(tmp_path):
    path = tmp_path / "conversation_log.csv"
    path.write_bytes(b"actor,message,tool_call,timestamp")
    append_row(
        path,
        LOG_FIELDS,
        {"actor": "user", "message": "hola", "tool_call": "", "timestamp": "2026-11-06T08:00:00+00:00"},
    )
    rows = read_rows(path, LOG_FIELDS)
    assert rows == [{"actor": "user", "message": "hola", "tool_call": "", "timestamp": "2026-11-06T08:00:00+00:00"}]


def test_failed_replace_leaves_the_original_file(tmp_path, monkeypatch):
    path = tmp_path / "products.csv"
    original_rows = [{"id": "1", "name": "Azúcar", "quantity": "5", "unit": "kg"}]
    replace_rows(path, PRODUCT_FIELDS, original_rows)
    original = path.read_bytes()

    def boom(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(safe_csv.os, "replace", boom)
    with pytest.raises(OSError):
        replace_rows(path, PRODUCT_FIELDS, [{"id": "1", "name": "Azúcar", "quantity": "0", "unit": "kg"}])
    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_concurrent_appends_do_not_drop_rows(tmp_path):
    path = tmp_path / "conversation_log.csv"

    def worker(index: int) -> None:
        for step in range(20):
            append_row(
                path,
                LOG_FIELDS,
                {
                    "actor": "user",
                    "message": f"{index}-{step}",
                    "tool_call": "",
                    "timestamp": "2026-11-06T08:00:00+00:00",
                },
            )

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = read_rows(path, LOG_FIELDS)
    assert len(rows) == 160
    assert {row["message"] for row in rows} == {f"{index}-{step}" for index in range(8) for step in range(20)}


def test_locked_read_modify_write_counts_every_increment(tmp_path):
    path = tmp_path / "products.csv"
    replace_rows(path, PRODUCT_FIELDS, [{"id": "1", "name": "Azúcar", "quantity": "0", "unit": "kg"}])

    def bump() -> None:
        def mutate(rows):
            current = int(rows[0]["quantity"])
            rows[0]["quantity"] = str(current + 1)
            return rows, True

        for _ in range(25):
            apply_rows(path, PRODUCT_FIELDS, mutate)

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert read_rows(path, PRODUCT_FIELDS)[0]["quantity"] == "100"
