"""Owner-click-only consent setup for autonomous plans' Google Drive file scope.

Reuses the existing private *desktop OAuth client* (not its read-only token).
The KLM read-only grant, launchd workers and Drive originals are untouched.
A successful owner grant is verified by an app-scoped metadata GET only.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import webbrowser

from .development_drive_oauth import BINDING, DriveFileToken, authorize
from .development_drive_plan import ScopedGooglePlanHTTP
from .klm_drive_auth import load_desktop_client

RUNTIME_RELATIVE = "Library/Application Support/AI-Foundation/klm-drive"
RESULT = "development-drive-consent-result.json"


def private_runtime(home=None):
    root = (Path.home() if home is None else Path(home)) / RUNTIME_RELATIVE
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or root.is_symlink()):
        raise PermissionError("EXISTING_PRIVATE_KLM_RUNTIME_REQUIRED")
    return root


def existing_client(runtime):
    """Same owner-installed Google client JSON, no new Cloud app or downloads."""
    path = Path(runtime) / "oauth-client.json"
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError("EXISTING_PRIVATE_OAUTH_CLIENT_REQUIRED")
    load_desktop_client(path)
    return path


def probe_app_file_scope(token_supplier, *, http_factory=ScopedGooglePlanHTTP):
    """GET-only, metadata-only; never creates a Doc merely to test consent."""
    http = http_factory(token_supplier)
    row = http.call(
        "drive", "GET", "/files",
        query={"q": "trashed = false", "pageSize": 1, "fields": "files(id)"})
    if type(row) is not dict or type(row.get("files")) is not list:
        raise ValueError("DRIVE_FILE_READ_PROBE_INVALID")
    return "DRIVE_FILE_METADATA_GET_VERIFIED"


def finish_consent(client, store, *, consent=authorize, open_browser=webbrowser.open,
                   probe=probe_app_file_scope):
    """No automatic launch: called only by an explicit owner's setup click.

    Reuse a still-valid exact app-only grant when present; a definitively
    expired own grant can be renewed by the owner's browser consent once.
    An unknown error remains blocked, never interpreted as an approval.
    """
    existing = store.available(BINDING)
    if existing:
        try:
            probe(DriveFileToken(store))
            return {"status": "DRIVE_FILE_CONSENT_ALREADY_VALID",
                    "scope_count": 1, "writer_enabled": False}
        except RuntimeError as exc:
            # Only definitive 400/401 token refresh rejection may renew.
            if str(exc) not in ("OAUTH_HTTP_400", "OAUTH_HTTP_401"):
                raise
    consent(client, store, open_browser=open_browser)
    probe(DriveFileToken(store))
    return {"status": "DRIVE_FILE_CONSENT_AND_READ_PROBE_VERIFIED",
            "scope_count": 1, "writer_enabled": False}


def write_result(runtime, report):
    """Atomic owner-private status with fixed vocabulary; never token fields."""
    report = dict(report)
    report["observed_at"] = time.time()
    allowed = {"status", "scope_count", "writer_enabled", "observed_at"}
    if set(report) != allowed or type(report["writer_enabled"]) is not bool:
        raise ValueError("PUBLIC_CONSENT_RESULT_INVALID")
    fd, name = tempfile.mkstemp(prefix=".consent-result-", dir=runtime)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(report, out, sort_keys=True)
        os.chmod(name, 0o600)
        os.replace(name, Path(runtime) / RESULT)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    options = argparse.ArgumentParser(description="Owner-only Drive plan consent")
    options.add_argument("--status", action="store_true", help="presence only; no token refresh")
    options.add_argument("--ssh-headless", action="store_true",
                         help="print Google URL for phone browser; no Mac GUI")
    options.add_argument("--port", type=int, default=8765,
                         help="SSH-forwarded loopback port (default 8765)")
    args = options.parse_args(argv)
    if (type(args.port) is not int or not 1024 <= args.port <= 65535):
        options.error("--port must be between 1024 and 65535")
    try:
        runtime = private_runtime()
        lock_path = runtime / "development-drive-consent.lock"
        lock = os.open(lock_path, os.O_CREAT | os.O_RDWR |
                       getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise PermissionError("CONSENT_LOCK_UNVERIFIED")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("認証画面はすでに開いています。そちらで操作してください。")
                return 0
            from .macos_keychain import MacOSKeychain
            store = MacOSKeychain()
            if args.status:
                bound = store.available(BINDING)
                print("同意情報あり（動作は未確認）" if bound else
                      "書込み同意がまだありません")
                return 0
            client = existing_client(runtime)
            print("ブラウザでGoogleの同意画面を開きます。"
                  "『このアプリで操作するファイルのみ』の権限を確認してください。",
                  flush=True)
            if args.ssh_headless:
                # Browser is on the owner's *phone*. The Android browser's
                # localhost callback reaches this Mac via SSH -L PORT:127.0.0.1:PORT.
                # The Mac itself never opens a browser or receives owner UI actions.
                print("SSHの -L ローカルポート転送を設定したスマホで、"
                      "次のGoogle URLを開き、権限を確認してください。",
                      flush=True)
                def owner_phone_url(url):
                    print("\\n--- Google同意URL（スマホのブラウザで開く） ---\\n"
                          + url + "\\n--- ここまで ---\\n", flush=True)
                    return True
                def phone_consent(path, vault, *, open_browser):
                    return authorize(path, vault, open_browser=owner_phone_url,
                                     redirect_port=args.port)
                report = finish_consent(client, store, consent=phone_consent)
            else:
                report = finish_consent(client, store)
            write_result(runtime, report)
            print("Google同意とDrive書込スコープの読み取り確認が完了しました。"
                  "計画書作成や本番サービスの変更はまだ実行していません。")
            return 0
        finally:
            os.close(lock)
    except Exception as exc:
        code = str(exc) if str(exc) in {
            "OAUTH_HTTP_400", "OAUTH_HTTP_401", "DRIVE_FILE_CONSENT_DENIED_OR_TIMED_OUT",
            "EXISTING_PRIVATE_KLM_RUNTIME_REQUIRED",
            "EXISTING_PRIVATE_OAUTH_CLIENT_REQUIRED",
        } else type(exc).__name__
        print("認証は完了していません。"
              "認証JSON・トークン・表示URLは共有せず、次のコードだけ知らせてください: "
              + code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
