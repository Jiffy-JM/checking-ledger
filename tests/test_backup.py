"""The optional cloud backup: the status the app shows, and the backup
script itself (run against a local encrypted repository when restic is
installed)."""
import json
import os
import pathlib
import re
import shutil
import subprocess
from datetime import date, datetime, timezone

import pytest

import backup_status
from app import create_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "backup" / "backup.sh"
NOW = datetime(2026, 9, 20, 15, 0, tzinfo=timezone.utc)
PASSWORD = "correct-horse-battery-staple-1"


def write(path, **fields):
    data = {"version": 1, "ok": True, "last_attempt": "2026-09-20T07:15:00Z",
            "last_success": "2026-09-20T07:15:00Z", "snapshots": 12, "message": ""}
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------- status reader

def test_no_file_means_not_set_up(tmp_path):
    assert backup_status.read_status(str(tmp_path / "missing.json"), NOW) is None
    assert backup_status.read_status("", NOW) is None


def test_a_recent_good_backup_is_ok(tmp_path):
    status = backup_status.read_status(write(tmp_path / "s.json"), NOW)
    assert (status.state, status.snapshots) == ("ok", 12)
    assert status.last_success == datetime(2026, 9, 20, 7, 15, tzinfo=timezone.utc)


def test_an_old_backup_is_stale_and_a_failed_one_is_failed(tmp_path):
    assert backup_status.read_status(write(tmp_path / "a.json", last_success="2026-09-17T07:15:00Z"), NOW).state == "stale"
    failed = backup_status.read_status(write(tmp_path / "b.json", ok=False, message="no route to host"), NOW)
    assert (failed.state, failed.message) == ("failed", "no route to host")


@pytest.mark.parametrize("junk", [b"", b"not json", b"[1, 2]", b'{"ok": true}', b'{"last_success": 5}',
                                  b'{"last_success": "yesterday"}', b"\xff\xfe", b"{" + b"x" * 10000])
def test_nonsense_in_the_file_is_ignored(tmp_path, junk):
    path = tmp_path / "s.json"
    path.write_bytes(junk)
    assert backup_status.read_status(str(path), NOW) is None


def test_odd_values_are_made_safe(tmp_path):
    status = backup_status.read_status(write(tmp_path / "s.json", snapshots="lots", message=["x"], ok="yes"), NOW)
    assert (status.state, status.snapshots, status.message) == ("failed", 0, "")
    long = backup_status.read_status(write(tmp_path / "t.json", message="a" * 5000), NOW)
    assert long is None or len(long.message) <= 200


# ------------------------------------------------------------------ the pages

@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")     # times on the pages follow the server's TZ setting


def make(tmp_path, status_file):
    app = create_app(data_dir=str(tmp_path / "data"), password="", today=lambda: date(2026, 9, 20),
                     backup_status_file=status_file, now=lambda: NOW)
    c = app.test_client()
    token = re.search(r'name="_csrf" value="([^"]+)"', c.get("/setup").get_data(as_text=True)).group(1)
    c.post("/setup", data={"_csrf": token, "balance": "3200", "date": "2026-09-01"})
    return c


def test_history_says_not_set_up_without_a_status_file(tmp_path):
    page = make(tmp_path, str(tmp_path / "none.json")).get("/history").get_data(as_text=True)
    assert "Cloud backup" in page and "Not set up" in page


def test_history_shows_the_last_backup(tmp_path):
    c = make(tmp_path, write(tmp_path / "s.json"))
    page = c.get("/history").get_data(as_text=True)
    assert "Backed up</span> Sep 20, 2026 at 7:15 AM" in page and "12 versions kept" in page
    assert "needs attention" not in c.get("/").get_data(as_text=True)


def test_a_failed_backup_is_flagged_on_overview_and_history(tmp_path):
    c = make(tmp_path, write(tmp_path / "s.json", ok=False, last_attempt="2026-09-20T07:15:00Z",
                             last_success="2026-09-19T07:15:00Z", message="<script>alert(1)</script> no route"))
    overview, history = c.get("/").get_data(as_text=True), c.get("/history").get_data(as_text=True)
    assert "Cloud backup needs attention" in overview
    assert "The most recent good backup is from Sep 19, 2026 at 7:15 AM" in history
    assert "<script>alert(1)" not in history and "&lt;script&gt;" in history


def test_a_stale_backup_is_flagged(tmp_path):
    c = make(tmp_path, write(tmp_path / "s.json", last_success="2026-09-10T07:15:00Z"))
    assert "No backup has finished since Sep 10, 2026" in c.get("/history").get_data(as_text=True)


# ------------------------------------------------------- how it is wired up

def test_the_app_container_gets_no_storage_keys_and_backup_cannot_write_data():
    yaml = pytest.importorskip("yaml")
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    app, backup = services["ledger"], services["backup"]
    assert "env_file" not in app
    assert not [k for k in app["environment"] if k.startswith(("AWS_", "RESTIC_"))]
    assert "./backup-status:/backup-status:ro" in app["volumes"]
    assert "./data:/data:ro" in backup["volumes"] and "./data:/data" not in backup["volumes"]
    assert backup["profiles"] == ["backup"]                       # off unless asked for
    assert re.fullmatch(r"restic/restic:\d+\.\d+\.\d+", backup["image"])   # pinned, never "latest"
    for service in (app, backup):
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]


def test_settings_template_holds_no_real_secrets_and_is_never_in_the_image():
    example = (ROOT / "backup.env.example").read_text(encoding="utf-8")
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "RESTIC_PASSWORD"):
        assert re.search(rf"^{key}=$", example, re.M), key
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for name in ("data/", ".env", "backup.env", "backup-status/", "restore/"):
        assert name in ignored, name
    assert "backup.env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


# ------------------------------------------------------------ the script

def run(tmp_path, *args, **env):
    settings = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "DATA_DIR": str(tmp_path / "data"),
                "STATUS_FILE": str(tmp_path / "status" / "status.json"), "RESTORE_DIR": str(tmp_path / "restore"),
                "RESTIC_CACHE_DIR": str(tmp_path / "cache"), "RESTIC_REPOSITORY": str(tmp_path / "repo"),
                "RESTIC_PASSWORD": PASSWORD}
    settings.update(env)
    return subprocess.run(["sh", str(SCRIPT), *args], env=settings, capture_output=True, text=True, timeout=120)


@pytest.fixture
def folders(tmp_path):
    for name in ("data", "status", "restore"):
        (tmp_path / name).mkdir()
    (tmp_path / "data" / "ledger.csv").write_text("id,type,date,amount\na1,balance,2026-09-01,3200.00\n", encoding="utf-8")
    (tmp_path / "data" / ".secret_key").write_text("session-signing-key", encoding="utf-8")
    return tmp_path


def test_script_refuses_weak_or_unencrypted_settings(folders):
    assert "at least 20 characters" in run(folders, "once", RESTIC_PASSWORD="short").stdout
    insecure = run(folders, "once", RESTIC_REPOSITORY="s3:http://example.invalid/bucket", AWS_ACCESS_KEY_ID="a", AWS_SECRET_ACCESS_KEY="b")
    assert insecure.returncode != 0 and "https://" in insecure.stdout
    assert run(folders, "once", RESTIC_REPOSITORY="rest:http://example.invalid/").returncode != 0
    assert "aren't set" in run(folders, "once", RESTIC_REPOSITORY="s3:https://example.invalid/bucket").stdout
    assert not (folders / "repo").exists()


needs_restic = pytest.mark.skipif(shutil.which("restic") is None, reason="restic isn't installed")


@needs_restic
def test_backup_is_encrypted_and_restores_exactly(folders):
    assert run(folders, "once").returncode == 0
    status = json.loads((folders / "status" / "status.json").read_text())
    assert status["ok"] is True and status["snapshots"] == 1
    stored = b"".join(p.read_bytes() for p in (folders / "repo").rglob("*") if p.is_file())
    for secret in (b"3200.00", b"ledger.csv", b"balance", b"session-signing-key"):
        assert secret not in stored
    assert run(folders, "restore").returncode == 0
    restored = list((folders / "restore").rglob("ledger.csv"))
    assert len(restored) == 1 and restored[0].read_bytes() == (folders / "data" / "ledger.csv").read_bytes()
    assert not list((folders / "restore").rglob(".secret_key"))        # the session key is left out


@needs_restic
def test_a_failed_backup_is_reported_as_failed_and_keeps_the_last_good_time(folders):
    assert run(folders, "once").returncode == 0
    good = json.loads((folders / "status" / "status.json").read_text())["last_success"]
    wrong = run(folders, "once", RESTIC_PASSWORD="this-is-not-the-right-password")
    status = json.loads((folders / "status" / "status.json").read_text())
    assert wrong.returncode != 0
    assert status["ok"] is False and status["last_success"] == good
    assert "does not match" in status["message"] and PASSWORD not in json.dumps(status)


@needs_restic
def test_status_file_never_contains_settings(folders):
    run(folders, "once", AWS_SECRET_ACCESS_KEY="super-secret-storage-key")
    text = (folders / "status" / "status.json").read_text()
    assert PASSWORD not in text and "super-secret-storage-key" not in text


@needs_restic
def test_the_log_and_status_never_show_keys_password_or_address(folders):
    """Whatever restic prints, the log hides the settings."""
    result = run(folders, "once", AWS_ACCESS_KEY_ID="key-id-0123456789", AWS_SECRET_ACCESS_KEY="super-secret-storage-key")
    wrong = run(folders, "once", RESTIC_PASSWORD="this-is-not-the-right-password")
    seen = result.stdout + result.stderr + wrong.stdout + wrong.stderr + (folders / "status" / "status.json").read_text()
    assert result.returncode == 0 and "snapshot" in seen
    for secret in (PASSWORD, "this-is-not-the-right-password", "key-id-0123456789", "super-secret-storage-key", str(folders / "repo")):
        assert secret not in seen
    assert "[storage address]" in seen                      # restic named the address; the log hid it


def test_redact_hides_each_setting_wherever_it_appears():
    env = {"PATH": os.environ["PATH"], "RESTIC_REPOSITORY": "s3:https://acct123.r2.cloudflarestorage.com/bucket/checking-ledger",
           "RESTIC_PASSWORD": PASSWORD, "AWS_ACCESS_KEY_ID": "key-id-0123456789", "AWS_SECRET_ACCESS_KEY": "super/secret+storage=key"}
    script = SCRIPT.read_text()
    start, end = script.index("STORAGE_HOST="), script.index("# -------------------------------------------------------------------- backup")
    said = ("Fatal: s3:https://acct123.r2.cloudflarestorage.com/bucket/checking-ledger refused key-id-0123456789\n"
            "Get https://acct123.r2.cloudflarestorage.com/bucket: super/secret+storage=key and correct-horse-battery-staple-1 twice super/secret+storage=key\n"
            "plain line\n")
    out = subprocess.run(["sh", "-c", script[start:end] + "\nredact"], input=said, env=env, capture_output=True, text=True).stdout
    assert out == ("Fatal: [storage address] refused [storage key id]\n"
                   "Get https://[storage host]/bucket: [storage secret] and [backup password] twice [storage secret]\n"
                   "plain line\n")
