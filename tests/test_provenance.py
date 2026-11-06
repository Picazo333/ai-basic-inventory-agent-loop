from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = ROOT / "third_party" / "python-hello"

EXPECTED = {
    "main.py": "eed9979879be4d18c16286d9439a2fc7d8744bb887d78bd2987e7fbadeb84a57",
    "server.py": "28e4573330cfb9b65bf984d2c4fe9d63e9032bf2f6a9e642268edf1d9a7f04af",
    "learn.json": "2e3adfaee4f2c92ad00a0157dbc36bdbe3c54b69a8c6fc83840418a3852973dc",
    "README.md": "269e30abb054bcb4504ddcc727bbb44e425274166ad0f9782da9aca0c9ee302f",
    "README.es.md": "dc3349cfadd525cd205f80ab0fbd17fa5fb3436d8c5b7c1cf09118ab42c22eb3",
}


def test_python_hello_snapshot_matches_the_origin_commit():
    provenance = (ORIGIN / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "142f2a913162efafce897da8bf241fe690f60395" in provenance
    assert "is_template" in provenance
    assert "ninguna" in provenance
    for name, digest in EXPECTED.items():
        payload = (ORIGIN / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest
        assert digest in provenance


def test_env_file_is_gitignored_and_not_present():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert not (ROOT / ".env").exists()
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "GROQ_API_KEY=" in example
    assert "gsk_" not in example
    assert "sk-" not in example
