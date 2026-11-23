"""User-started setup: fresh Google client download -> existing native OAuth.

No permanent watcher, credential discovery in apps, secret logs, or new scheduler.
"""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import webbrowser

from .klm_drive_auth import authorize, load_desktop_client, ReadonlyGoogleToken

CLIENTS_URL = 'https://console.cloud.google.com/auth/clients'
GUIDE = '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI-Foundation：Google読取認証</title>
<style>body{font:17px/1.8 system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 24px;color:#172331;background:#f4f7fa}section{background:white;border-radius:16px;padding:24px;margin:18px 0}a{color:#1359af}h1{font-size:27px}h2{font-size:20px}strong{color:#124f86}</style>
<h1>Googleの初回設定だけお願いします</h1>
<p>この画面を開いたアプリが、ダウンロードと認証の完了を待っています。ファイルの移動・名前変更・パス入力は不要です。</p>
<section><h2>1. 同じGoogle Cloudプロジェクトを選ぶ</h2>
<p>プロジェクトが未作成なら、Google画面の案内で作成してください。アプリ名は <strong>AI-Foundation KLM</strong>、連絡先は自分のGoogleアカウントを使用します。料金のかかるサービスは使いません。請求先登録を求められた場合は進まず、ここで知らせてください。</p>
<p>そのプロジェクトで <a target="_blank" rel="noopener" href="https://console.cloud.google.com/apis/library/drive.googleapis.com">Google Drive API</a> と <a target="_blank" rel="noopener" href="https://console.cloud.google.com/apis/library/sheets.googleapis.com">Google Sheets API</a> を有効にします。</p></section>
<section><h2>2. デスクトップ用の設定JSONをダウンロード</h2>
<p><a target="_blank" rel="noopener" href="https://console.cloud.google.com/auth/clients">Google Auth Platformのクライアント画面</a> →「クライアントを作成」→種類 <strong>デスクトップアプリ</strong> → 作成 → JSONをダウンロード。</p>
<p>Googleの案内で同意画面・対象ユーザーの設定が求められた場合は、自分用のアプリとして自分のアカウントを指定します。設定方法は <a target="_blank" rel="noopener" href="https://developers.google.com/workspace/guides/create-credentials?hl=ja#desktop-app">Google公式手順</a> を参照してください。</p>
<p>保存先は通常の「ダウンロード」。Google既定の <code>client_secret…json</code> または <code>credentials.json</code> のままにします。20分以内に、この起動後にダウンロードした1個を自動で取り込みます。ダウンロード先に以前からあるJSONは自動選択しません。時間切れでも同じ入口を開き直せます。</p></section>
<section><h2>3. 自動で開くGoogle同意画面で許可</h2>
<p>取り込み後は自動で認証画面が開きます。自分のDriveのアカウントを選び、<strong>Driveとスプレッドシートの読み取り専用</strong>の要求内容を確認して同意してください。確認できないアプリ・アカウントの場合は同意せず知らせてください。</p>
<p>その後はKeychain保存、読取確認、既存の定期処理への接続まで自動です。開発タスクがある間は9B推論を待機します。実際の全件同期・無人運転の受入は別途結果を確認します。</p></section>
<p>認証JSONや認証コードをチャットに貼る必要はありません。設定が未完了・取り消しでも、元のDriveや既存の認証は変更しません。</p></html>'''


def fresh_downloads(downloads, started_at, previous):
    """Only new, stable Google export filenames in the user's Downloads folder."""
    downloads = Path(downloads)
    if not downloads.is_dir() or downloads.is_symlink():
        return [], {}
    paths = set(downloads.glob('client_secret*.json')) | set(downloads.glob('credentials*.json'))
    current, ready = {}, []
    for path in paths:
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or not 0 < info.st_size <= 65536 or info.st_mtime < started_at):
                continue
            fingerprint = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            current[str(path)] = fingerprint
            if previous.get(str(path)) == fingerprint:
                ready.append(path)
        except OSError:
            continue
    return ready, current


def import_client(source, destination):
    """Private validated copy; never overwrite an existing client or follow links."""
    source, destination = Path(source), Path(destination)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(source, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
            raise PermissionError('OWNER_CLIENT_FILE_REQUIRED')
        raw = os.read(fd, 65537)
        after = os.fstat(fd)
        if (len(raw) > 65536 or before.st_size != len(raw)
                or before.st_mtime_ns != after.st_mtime_ns
                or (source.lstat().st_dev, source.lstat().st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('CLIENT_DOWNLOAD_NOT_STABLE')
    finally:
        os.close(fd)
    tmp_fd, name = tempfile.mkstemp(prefix='.google-client-', dir=destination.parent)
    try:
        with os.fdopen(tmp_fd, 'wb') as out:
            out.write(raw)
        load_desktop_client(name)  # unchanged approved Google desktop validator
        os.link(name, destination)  # exclusive publication; no replace/overwrite
    finally:
        os.unlink(name)
    return destination


def acquire_client(runtime, *, downloads, started_at, timeout=1200,
                   open_browser=webbrowser.open, clock=time.time, sleep=time.sleep):
    runtime = Path(runtime)
    destination = runtime / 'oauth-client.json'
    if destination.exists() or destination.is_symlink():
        load_desktop_client(destination)
        return destination
    guide = runtime / '認証のはじめかた.html'
    if guide.is_symlink():
        raise PermissionError('PRIVATE_GUIDE_REQUIRED')
    guide.write_text(GUIDE)
    guide.chmod(0o600)
    if open_browser(guide.as_uri()) is False:
        raise RuntimeError('SYSTEM_BROWSER_UNAVAILABLE')
    previous = {}
    deadline = clock() + timeout
    while clock() < deadline:
        candidates, previous = fresh_downloads(downloads, started_at, previous)
        valid = []
        for path in candidates:
            try:
                load_desktop_client(path)
                valid.append(path)
            except (ValueError, OSError):
                pass
        if len(valid) > 1:
            raise RuntimeError('MULTIPLE_FRESH_GOOGLE_CLIENTS')
        if len(valid) == 1:
            return import_client(valid[0], destination)
        sleep(1)
    raise TimeoutError('CLIENT_DOWNLOAD_WAIT_TIMED_OUT')


def finish_setup(client, store, *, consent=authorize, open_browser=webbrowser.open,
                 probe, resume):
    token = ReadonlyGoogleToken(store)
    new_consent = False
    if not token.available():
        consent(client, store, open_browser=open_browser)
        new_consent = True
    # A grant alone is not proof that APIs/account/scope work. Never resume on failure.
    try:
        probe(ReadonlyGoogleToken(store))
    except RuntimeError as exc:
        if new_consent or str(exc) not in {'OAUTH_HTTP_400', 'OAUTH_HTTP_401'}:
            raise
        # Expired/revoked own refresh grant: one consent retry, no deletion or
        # credential scavenging, and preserve the old binding if consent fails.
        consent(client, store, open_browser=open_browser)
        probe(ReadonlyGoogleToken(store))
    resume()
    return {'status': 'AUTH_BOUND_READ_PROBE_PASSED_TICK_REQUESTED',
            'observed_at': time.time(), 'klm_unattended_accepted': False}


def main():
    from .macos_keychain import MacOSKeychain
    from .klm_drive_input import ReadOnlyDriveAPI
    from .klm_drive_runtime import OwnerDriveHTTP, OwnerInboxHTTP
    from .klm_drive_cycle import NativeInboxReader
    from . import klm_drive_auth
    runtime = Path.home() / 'Library/Application Support/AI-Foundation/klm-drive'
    info = runtime.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError('EXISTING_PRIVATE_RUNTIME_REQUIRED')
    lock = os.open(runtime / 'auth-helper.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('認証設定はすでに開いています。その画面を続けてください。')
            return 0
        store = MacOSKeychain()
        client = runtime / 'oauth-client.json'
        if not store.available(klm_drive_auth.BINDING):
            print('案内をブラウザで開きます。JSONのダウンロード後は自動で認証へ進みます。', flush=True)
            client = acquire_client(runtime, downloads=Path.home() / 'Downloads', started_at=time.time())
        config = json.loads((runtime / 'host.json').read_text())
        def probe(token):
            drive = ReadOnlyDriveAPI(OwnerDriveHTTP(token))
            for root in config['roots']:
                if drive.get_metadata(root).get('id') != root:
                    raise ValueError('APPROVED_ROOT_READBACK_FAILED')
            NativeInboxReader(OwnerInboxHTTP(token)).values()
        def resume():
            subprocess.run(['/bin/launchctl', 'kickstart', 'gui/' + str(os.getuid()) +
                            '/dev.quest7070.ai-foundation.klm-drive'], check=True, timeout=10)
        result = finish_setup(client, store, probe=probe, resume=resume)
        report = runtime / 'auth-setup-result.json'
        fd, name = tempfile.mkstemp(prefix='.auth-result-', dir=runtime)
        with os.fdopen(fd, 'w') as out:
            json.dump(result, out)
        os.replace(name, report)
        print('認証と読取確認が完了しました。定期処理へ接続しました。開発処理があれば整理は待機します。')
        return 0
    except Exception as exc:
        # No OAuth URL/code, client secret, token, file text or provider diagnostics.
        messages = {
            'CLIENT_DOWNLOAD_WAIT_TIMED_OUT': 'JSON待ちが時間切れになりました。同じ入口を開き直してください。',
            'MULTIPLE_FRESH_GOOGLE_CLIENTS': '新しい設定JSONが複数あります。認証情報を貼らず、この状況を知らせてください。',
            'OAUTH_DENIED_OR_TIMED_OUT': 'Googleの同意が完了していません。同じ入口からやり直せます。',
            'DRIVE_HTTP_403': 'Google側のAPI有効化・同意内容・アカウントを案内画面で確認してください。',
            'DRIVE_HTTP_404': '指定のDrive資料を読めません。選んだGoogleアカウントを確認してください。',
        }
        code = str(exc) if str(exc) in messages else type(exc).__name__
        print('設定は完了していません。' + messages.get(code, '認証情報を貼らず、次のコードを知らせてください：' + code))
        return 2
    finally:
        os.close(lock)


if __name__ == '__main__':
    raise SystemExit(main())
