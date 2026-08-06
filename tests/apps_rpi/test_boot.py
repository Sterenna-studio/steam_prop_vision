"""
tests/apps_rpi/test_boot.py
Tests unitaires pour apps.rpi.boot (checks de démarrage + nettoyage des
processus orphelins). shutil.which/subprocess.run sont mockés — aucune
dépendance à un vrai mpv/ffplay installé.
"""

from __future__ import annotations

import pytest

from apps.rpi import boot


def test_kill_orphan_players_calls_pkill_for_known_players(monkeypatch):
    monkeypatch.setattr(
        boot.shutil, "which", lambda name: "/usr/bin/pkill" if name == "pkill" else None
    )
    calls = []
    monkeypatch.setattr(
        boot.subprocess, "run", lambda args, **kwargs: calls.append(args)
    )

    boot._kill_orphan_players()

    assert calls == [["pkill", "-x", "mpv"], ["pkill", "-x", "ffplay"]]


def test_kill_orphan_players_noop_without_pkill(monkeypatch):
    monkeypatch.setattr(boot.shutil, "which", lambda name: None)
    calls = []
    monkeypatch.setattr(boot.subprocess, "run", lambda *a, **k: calls.append(a))

    boot._kill_orphan_players()

    assert calls == []


@pytest.fixture
def hermetic_cwd(tmp_path, monkeypatch):
    (tmp_path / "PLATEST" / "plate_test").mkdir(parents=True)
    (tmp_path / "PLATEST" / "plate_test" / "img.jpg").write_bytes(b"")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "rules.yaml").write_text("rules: {}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_boot_checks_passes_with_all_dependencies_present(monkeypatch, hermetic_cwd):
    monkeypatch.setattr(
        boot.shutil,
        "which",
        lambda name: ("/usr/bin/" + name)
        if name in ("mpv", "aplay", "pkill")
        else None,
    )
    monkeypatch.setattr(boot.subprocess, "run", lambda *a, **k: None)

    boot.boot_checks()  # ne doit pas lever


def test_boot_checks_aborts_without_video_player(monkeypatch, hermetic_cwd):
    monkeypatch.setattr(boot.shutil, "which", lambda name: None)
    monkeypatch.setattr(boot.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(SystemExit):
        boot.boot_checks()


def test_boot_checks_aborts_without_platest(monkeypatch, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "rules.yaml").write_text("rules: {}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        boot.shutil, "which", lambda name: "/usr/bin/mpv" if name == "mpv" else None
    )
    monkeypatch.setattr(boot.subprocess, "run", lambda *a, **k: None)

    with pytest.raises(SystemExit):
        boot.boot_checks()
