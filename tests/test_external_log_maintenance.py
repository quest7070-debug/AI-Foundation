from __future__ import annotations
import subprocess

import gzip
import threading
from pathlib import Path

import pytest

import ai_foundation.external_log_maintenance as module
from ai_foundation.external_log_maintenance import (
    ExternalLogMaintenance,
    ExternalLogPolicy,
    MaintenanceStatus,
)


class FakeOwner:
    def __init__(
        self,
        *,
        running: bool = True,
        closes: bool = True,
        ready: bool = True,
        fail_stop: bool = False,
        fail_start: bool = False,
    ) -> None:
        self.running = running
        self.closes = closes
        self.ready = ready
        self.fail_stop = fail_stop
        self.fail_start = fail_start

        self.stop_calls = 0
        self.start_calls = 0
        self.readback_calls = 0
        self.close_calls = 0

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        self.stop_calls += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")
        self.running = False

    def wait_log_closed(self, path: Path) -> bool:
        self.close_calls += 1
        return self.closes

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError("start failed")
        self.running = True

    def readback_ready(self) -> bool:
        self.readback_calls += 1
        return self.running and self.ready


def policy(
    path: Path,
    *,
    max_bytes: int = 8,
    backups: int = 3,
) -> ExternalLogPolicy:
    return ExternalLogPolicy(
        path=path,
        max_bytes=max_bytes,
        backup_count=backups,
    )


def read_gzip(path: Path) -> bytes:
    with gzip.open(path, "rb") as handle:
        return handle.read()


def test_policy_rejects_invalid_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        policy(tmp_path / "x.log", max_bytes=0)

    with pytest.raises(ValueError):
        policy(tmp_path / "x.log", backups=0)


def test_missing_log_is_noop(tmp_path: Path) -> None:
    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(tmp_path / "missing.log"),
        owner,
    )

    assert result.status is MaintenanceStatus.NOOP
    assert result.detail == "log-missing"
    assert owner.stop_calls == 0


def test_below_threshold_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"small")
    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path, max_bytes=100),
        owner,
    )

    assert result.status is MaintenanceStatus.NOOP
    assert owner.stop_calls == 0
    assert owner.close_calls == 0
    assert path.read_bytes() == b"small"


def test_running_owner_rotates_then_recovers_before_archive(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    payload = b"x" * 32
    path.write_bytes(payload)

    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert result.rotated
    assert result.recovered

    assert owner.stop_calls == 1
    assert owner.close_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1

    assert not (tmp_path / "service.log.lt05-pending").exists()
    assert read_gzip(tmp_path / "service.log.1.gz") == payload


def test_stopped_owner_remains_stopped_but_fd_close_is_required(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"x" * 32)

    owner = FakeOwner(running=False)

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert owner.stop_calls == 0
    assert owner.start_calls == 0
    assert owner.readback_calls == 0
    assert owner.close_calls == 1
    assert owner.running is False


def test_stopped_owner_with_open_fd_fails_without_rotation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    original = b"x" * 32
    path.write_bytes(original)

    owner = FakeOwner(running=False, closes=False)

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert not result.rotated
    assert result.recovered
    assert path.read_bytes() == original
    assert owner.start_calls == 0


def test_running_owner_open_fd_failure_restores_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"x" * 32)

    owner = FakeOwner(closes=False)

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert not result.rotated
    assert result.recovered
    assert owner.stop_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1


def test_active_rename_failure_restores_owner_and_keeps_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"
    original = b"x" * 32
    path.write_bytes(original)

    real_replace = module.os.replace

    def fail_active(src, dst):
        if Path(src) == path:
            raise OSError("injected rename failure")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", fail_active)

    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert not result.rotated
    assert result.recovered
    assert path.read_bytes() == original
    assert owner.start_calls == 1


def test_start_failure_has_only_one_recovery_start_attempt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"x" * 32)

    owner = FakeOwner(fail_start=True)

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_UNRECOVERED
    assert result.rotated
    assert not result.recovered

    # normal start + exactly one bounded recovery start
    assert owner.start_calls == 2
    assert (
        tmp_path / "service.log.lt05-pending"
    ).exists()


def test_readback_failure_performs_exactly_one_bounded_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"x" * 32)

    owner = FakeOwner(ready=False)

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_UNRECOVERED
    assert result.rotated
    assert not result.recovered

    # Normal lifecycle:
    #   stop -> start -> failed readback
    #
    # One bounded recovery lifecycle:
    #   stop -> start -> failed readback
    #
    # There is no third attempt.
    assert owner.stop_calls == 2
    assert owner.start_calls == 2
    assert owner.readback_calls == 2


def test_pending_is_recovered_before_new_active_rotation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"new-active" * 4)

    pending = tmp_path / "service.log.lt05-pending"
    pending.write_bytes(b"old-pending")

    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path, max_bytes=1),
        owner,
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert not result.rotated
    assert result.detail == "pending-recovered"

    assert owner.stop_calls == 0
    assert path.read_bytes() == b"new-active" * 4
    assert read_gzip(tmp_path / "service.log.1.gz") == b"old-pending"


def test_compression_failure_keeps_pending_and_service_recovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"
    payload = b"x" * 32
    path.write_bytes(payload)

    class BrokenGzip:
        def __enter__(self):
            raise OSError("ENOSPC")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        module.gzip,
        "open",
        lambda *args, **kwargs: BrokenGzip(),
    )

    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert result.rotated
    assert result.recovered

    assert owner.running
    assert owner.start_calls == 1
    assert (
        tmp_path / "service.log.lt05-pending"
    ).read_bytes() == payload


def test_pending_archive_failure_never_rotates_new_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"
    active = b"active" * 8
    old = b"pending"
    path.write_bytes(active)

    pending = tmp_path / "service.log.lt05-pending"
    pending.write_bytes(old)

    class BrokenGzip:
        def __enter__(self):
            raise OSError("disk full")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        module.gzip,
        "open",
        lambda *args, **kwargs: BrokenGzip(),
    )

    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path, max_bytes=1),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert not result.rotated
    assert path.read_bytes() == active
    assert pending.read_bytes() == old
    assert owner.stop_calls == 0


def test_retention_converges_to_three_generations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    maintenance = ExternalLogMaintenance()
    owner = FakeOwner()

    payloads = []

    for index in range(6):
        payload = bytes([index]) * 32
        payloads.append(payload)
        path.write_bytes(payload)

        result = maintenance.run_once(
            policy(path, backups=3),
            owner,
        )
        assert result.status is MaintenanceStatus.SUCCESS

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == payloads[-1]

    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == payloads[-2]

    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == payloads[-3]

    assert not (
        tmp_path / "service.log.4.gz"
    ).exists()


def test_stale_compression_temp_is_rebuilt_from_pending(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"

    pending = tmp_path / "service.log.lt05-pending"
    pending.write_bytes(b"authoritative")

    stale = tmp_path / "service.log.lt05-compressing"
    stale.write_bytes(b"partial")

    result = ExternalLogMaintenance().run_once(
        policy(path),
        FakeOwner(),
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert result.detail == "pending-recovered"
    assert not stale.exists()
    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == b"authoritative"


def test_interrupted_archive_staging_resumes_from_transaction_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"

    pending = tmp_path / "service.log.lt05-pending"
    pending.write_bytes(b"authoritative")

    for generation, payload in (
        (1, b"old-1"),
        (2, b"old-2"),
        (3, b"old-3"),
    ):
        with gzip.open(
            tmp_path / f"service.log.{generation}.gz",
            "wb",
        ) as handle:
            handle.write(payload)

    maintenance = ExternalLogMaintenance()
    real_replace = module.os.replace
    calls = 0

    def fail_during_staging(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected staging crash")
        return real_replace(src, dst)

    monkeypatch.setattr(
        module.os,
        "replace",
        fail_during_staging,
    )

    first = maintenance.run_once(
        policy(path),
        FakeOwner(),
    )

    assert first.status is MaintenanceStatus.FAILED_RECOVERED
    assert not first.rotated
    assert pending.read_bytes() == b"authoritative"

    txn = tmp_path / "service.log.lt05-archive-txn"
    assert txn.is_dir()
    assert not (txn / "STAGED").exists()

    monkeypatch.setattr(
        module.os,
        "replace",
        real_replace,
    )

    second = maintenance.run_once(
        policy(path),
        FakeOwner(),
    )

    assert second.status is MaintenanceStatus.SUCCESS
    assert second.detail == "pending-recovered"

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == b"authoritative"
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == b"old-1"
    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == b"old-2"

    assert not pending.exists()
    assert not txn.exists()


def test_concurrent_run_is_suppressed(tmp_path: Path) -> None:
    maintenance = ExternalLogMaintenance()
    path = tmp_path / "service.log"
    path.write_bytes(b"x" * 32)

    entered = threading.Event()
    release = threading.Event()

    class BlockingOwner(FakeOwner):
        def wait_log_closed(self, path: Path) -> bool:
            self.close_calls += 1
            entered.set()
            assert release.wait(timeout=2)
            return True

    owner = BlockingOwner()
    results = []

    thread = threading.Thread(
        target=lambda: results.append(
            maintenance.run_once(policy(path), owner)
        )
    )
    thread.start()

    assert entered.wait(timeout=2)

    concurrent = maintenance.run_once(
        policy(path),
        FakeOwner(),
    )

    assert concurrent.status is MaintenanceStatus.NOOP
    assert concurrent.detail == "maintenance-already-running"

    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    assert results[0].status is MaintenanceStatus.SUCCESS


def test_interrupted_archive_transaction_retries_from_immutable_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"
    newest = b"newest" * 16
    path.write_bytes(newest)

    for generation, payload in (
        (1, b"old-1"),
        (2, b"old-2"),
        (3, b"old-3"),
    ):
        with gzip.open(
            tmp_path / f"service.log.{generation}.gz",
            "wb",
        ) as handle:
            handle.write(payload)

    owner = FakeOwner()
    maintenance = ExternalLogMaintenance()

    real_replace = module.os.replace
    calls = 0

    def fail_late(src, dst):
        nonlocal calls
        calls += 1
        # Deliberately fail after staging has begun/publishing is reachable.
        if calls == 7:
            raise OSError("injected late archive failure")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", fail_late)

    first = maintenance.run_once(
        policy(path, max_bytes=1, backups=3),
        owner,
    )

    assert first.status is MaintenanceStatus.FAILED_RECOVERED
    assert first.rotated
    assert first.recovered
    assert owner.running

    pending = tmp_path / "service.log.lt05-pending"
    assert pending.exists()

    # Remove failure injection.  Retry must use the transaction baseline,
    # not infer state from partially published root generations.
    monkeypatch.setattr(module.os, "replace", real_replace)

    second = maintenance.run_once(
        policy(path, max_bytes=1, backups=3),
        owner,
    )

    assert second.status is MaintenanceStatus.SUCCESS
    assert second.detail == "pending-recovered"

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == newest
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == b"old-1"
    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == b"old-2"

    assert not pending.exists()
    assert not (
        tmp_path / "service.log.lt05-archive-txn"
    ).exists()


def test_archive_transaction_preserves_original_absent_generations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"newest" * 16)

    with gzip.open(
        tmp_path / "service.log.1.gz",
        "wb",
    ) as handle:
        handle.write(b"only-old-1")

    result = ExternalLogMaintenance().run_once(
        policy(path, max_bytes=1, backups=3),
        FakeOwner(),
    )

    assert result.status is MaintenanceStatus.SUCCESS

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == b"newest" * 16
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == b"only-old-1"
    assert not (
        tmp_path / "service.log.3.gz"
    ).exists()


def test_partial_published_marker_cleanup_failure_cannot_erase_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"
    newest = b"newest" * 32
    path.write_bytes(newest)

    originals = {
        1: b"old-1",
        2: b"old-2",
        3: b"old-3",
    }

    for generation, payload in originals.items():
        with gzip.open(
            tmp_path / f"service.log.{generation}.gz",
            "wb",
        ) as handle:
            handle.write(payload)

    maintenance = ExternalLogMaintenance()
    real_rmtree = module.shutil.rmtree
    injected = False

    def partial_marker_cleanup_failure(target):
        nonlocal injected
        target = Path(target)

        if (
            not injected
            and target.name
            == "service.log.lt05-archive-published"
        ):
            injected = True

            # Publication is already committed and pending has already been
            # retired when this cleanup runs. Partial destruction here may
            # damage only the retired marker, never published generations.
            victim = target / "1.gz"
            if victim.exists():
                victim.unlink()

            raise OSError(
                "injected partial published-marker cleanup failure"
            )

        return real_rmtree(target)

    monkeypatch.setattr(
        module.shutil,
        "rmtree",
        partial_marker_cleanup_failure,
    )

    first = maintenance.run_once(
        policy(path, max_bytes=1, backups=3),
        FakeOwner(),
    )

    assert first.status is MaintenanceStatus.SUCCESS
    assert first.rotated

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == newest
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == originals[1]
    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == originals[2]

    pending = tmp_path / "service.log.lt05-pending"
    txn = tmp_path / "service.log.lt05-archive-txn"
    published = (
        tmp_path / "service.log.lt05-archive-published"
    )

    assert not pending.exists()
    assert not txn.exists()

    # Cleanup failure may leave a partially removed marker, but with pending
    # gone it is no longer correctness authority.
    assert published.exists()

    second = maintenance.run_once(
        policy(path, max_bytes=10**9, backups=3),
        FakeOwner(),
    )

    assert second.status is MaintenanceStatus.NOOP
    assert not second.rotated
    assert not published.exists()

    # Retired-marker cleanup must never shift or erase root generations.
    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == newest
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == originals[1]
    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == originals[2]

def test_group_rotates_two_paths_with_one_owner_restart(
    tmp_path: Path,
) -> None:
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    stdout_payload = b"stdout" * 16
    stderr_payload = b"stderr" * 16
    stdout.write_bytes(stdout_payload)
    stderr.write_bytes(stderr_payload)

    owner = FakeOwner()
    maintenance = ExternalLogMaintenance()

    result = maintenance.run_group(
        (
            policy(stdout, max_bytes=1),
            policy(stderr, max_bytes=1),
        ),
        owner,
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert result.rotated
    assert owner.stop_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1
    assert owner.close_calls == 2

    assert read_gzip(
        tmp_path / "stdout.log.1.gz"
    ) == stdout_payload
    assert read_gzip(
        tmp_path / "stderr.log.1.gz"
    ) == stderr_payload


def test_group_checks_all_descriptors_before_first_rename(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    first_payload = b"first" * 16
    second_payload = b"second" * 16
    first.write_bytes(first_payload)
    second.write_bytes(second_payload)

    class SecondOpenOwner(FakeOwner):
        def wait_log_closed(self, path: Path) -> bool:
            self.close_calls += 1
            return path != second

    owner = SecondOpenOwner()

    result = ExternalLogMaintenance().run_group(
        (
            policy(first, max_bytes=1),
            policy(second, max_bytes=1),
        ),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert owner.stop_calls == 1
    assert owner.start_calls == 1
    assert first.read_bytes() == first_payload
    assert second.read_bytes() == second_payload
    assert not (tmp_path / "first.log.lt05-pending").exists()
    assert not (tmp_path / "second.log.lt05-pending").exists()


def test_group_rotates_only_oversized_path_but_restarts_once(
    tmp_path: Path,
) -> None:
    large = tmp_path / "large.log"
    small = tmp_path / "small.log"
    large_payload = b"x" * 64
    small_payload = b"small"
    large.write_bytes(large_payload)
    small.write_bytes(small_payload)

    owner = FakeOwner()

    result = ExternalLogMaintenance().run_group(
        (
            policy(large, max_bytes=8),
            policy(small, max_bytes=100),
        ),
        owner,
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert owner.stop_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1
    assert owner.close_calls == 1

    assert read_gzip(
        tmp_path / "large.log.1.gz"
    ) == large_payload
    assert small.read_bytes() == small_payload


def test_group_deduplicates_identical_physical_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shared.log"
    payload = b"x" * 64
    path.write_bytes(payload)

    owner = FakeOwner()
    same = policy(path, max_bytes=1)

    result = ExternalLogMaintenance().run_group(
        (same, same),
        owner,
    )

    assert result.status is MaintenanceStatus.SUCCESS
    assert len(result.results) == 1
    assert owner.stop_calls == 1
    assert owner.close_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1
    assert read_gzip(
        tmp_path / "shared.log.1.gz"
    ) == payload


def test_group_rejects_conflicting_policy_for_same_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shared.log"
    path.write_bytes(b"x" * 64)

    with pytest.raises(ValueError):
        ExternalLogMaintenance().run_group(
            (
                policy(path, max_bytes=1),
                policy(path, max_bytes=2),
            ),
            FakeOwner(),
        )


def test_run_once_preserves_single_path_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    payload = b"x" * 64
    path.write_bytes(payload)
    owner = FakeOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path, max_bytes=1),
        owner,
    )

    assert isinstance(result, module.MaintenanceResult)
    assert result.status is MaintenanceStatus.SUCCESS
    assert result.rotated
    assert owner.stop_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1


def test_group_second_active_move_failure_converges_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"

    stdout_payload = b"stdout-before\n" * 16
    stderr_payload = b"stderr-before\n" * 16

    stdout.write_bytes(stdout_payload)
    stderr.write_bytes(stderr_payload)

    class ReopeningOwner(FakeOwner):
        def __init__(self) -> None:
            super().__init__()
            self.paths = (stdout, stderr)

        def start(self) -> None:
            super().start()

            for owned_path in self.paths:
                if not owned_path.exists():
                    owned_path.write_bytes(b"restarted\n")

    owner = ReopeningOwner()
    maintenance = ExternalLogMaintenance()

    policies = (
        policy(stdout, max_bytes=1),
        policy(stderr, max_bytes=1),
    )

    real_replace = module.os.replace
    active_moves = 0

    def fail_second_active_move(src, dst):
        nonlocal active_moves

        src = Path(src)
        dst = Path(dst)

        if dst.name.endswith(".lt05-pending"):
            active_moves += 1

            if active_moves == 2:
                raise OSError(
                    "injected second active move failure"
                )

        return real_replace(src, dst)

    monkeypatch.setattr(
        module.os,
        "replace",
        fail_second_active_move,
    )

    first = maintenance.run_group(
        policies,
        owner,
    )

    assert first.status is MaintenanceStatus.FAILED_RECOVERED
    assert first.rotated
    assert first.recovered

    assert owner.running
    assert owner.stop_calls == 1
    assert owner.start_calls == 1
    assert owner.readback_calls == 1
    assert owner.close_calls == 2

    stdout_pending = (
        tmp_path / "stdout.log.lt05-pending"
    )
    stderr_pending = (
        tmp_path / "stderr.log.lt05-pending"
    )

    assert stdout.exists()
    assert stdout_pending.exists()

    assert stderr.exists()
    assert not stderr_pending.exists()

    monkeypatch.setattr(
        module.os,
        "replace",
        real_replace,
    )

    second = maintenance.run_group(
        policies,
        owner,
    )

    assert second.status is MaintenanceStatus.SUCCESS
    assert second.rotated
    assert second.recovered

    assert read_gzip(
        tmp_path / "stdout.log.1.gz"
    ) == stdout_payload

    assert read_gzip(
        tmp_path / "stderr.log.1.gz"
    ) == stderr_payload

    assert not stdout_pending.exists()
    assert not stderr_pending.exists()

    assert owner.running

    # One lifecycle for the failed first attempt, one lifecycle for the
    # still-active stderr path on retry.
    assert owner.stop_calls == 2
    assert owner.start_calls == 2
    assert owner.readback_calls == 2


def test_external_log_maintenance_lease_acquires_and_releases(
    tmp_path: Path,
) -> None:
    lease = module.ExternalLogMaintenanceLease(
        tmp_path / "external-log-maintenance.lock"
    )

    with lease.acquire() as acquired:
        assert acquired is True

    with lease.acquire() as acquired:
        assert acquired is True


def test_external_log_maintenance_lease_is_nonblocking_across_processes(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys

    lock_path = tmp_path / "external-log-maintenance.lock"

    holder_code = r"""
import fcntl
import pathlib
import sys
import time

path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)

with open(path, "a+b") as handle:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    print("LOCKED", flush=True)
    time.sleep(10)
"""

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            holder_code,
            str(lock_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "LOCKED"

        lease = module.ExternalLogMaintenanceLease(lock_path)

        with lease.acquire() as acquired:
            assert acquired is False

    finally:
        holder.terminate()
        holder.wait(timeout=5)

    # Kernel releases the descriptor lock when the holder exits.
    with module.ExternalLogMaintenanceLease(
        lock_path
    ).acquire() as acquired:
        assert acquired is True


def test_external_log_maintenance_lease_does_not_mutate_logs_when_busy(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys

    lock_path = tmp_path / "external-log-maintenance.lock"
    log_path = tmp_path / "service.log"
    payload = b"unchanged"
    log_path.write_bytes(payload)

    holder_code = r"""
import fcntl
import pathlib
import sys
import time

path = pathlib.Path(sys.argv[1])

with open(path, "a+b") as handle:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    print("LOCKED", flush=True)
    time.sleep(10)
"""

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            holder_code,
            str(lock_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "LOCKED"

        maintenance = ExternalLogMaintenance()
        owner = FakeOwner()

        with module.ExternalLogMaintenanceLease(
            lock_path
        ).acquire() as acquired:
            if acquired:
                maintenance.run_once(
                    policy(log_path, max_bytes=1),
                    owner,
                )

        assert acquired is False
        assert log_path.read_bytes() == payload
        assert owner.stop_calls == 0
        assert owner.start_calls == 0
        assert owner.close_calls == 0
        assert owner.readback_calls == 0

    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_readback_failure_can_recover_on_one_bounded_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "service.log"
    path.write_bytes(b"x" * 32)

    class RecoveringOwner(FakeOwner):
        def readback_ready(self) -> bool:
            self.readback_calls += 1
            return self.readback_calls >= 2

    owner = RecoveringOwner()

    result = ExternalLogMaintenance().run_once(
        policy(path),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert result.rotated
    assert result.recovered

    assert owner.stop_calls == 2
    assert owner.start_calls == 2
    assert owner.readback_calls == 2

    # The failed maintenance operation leaves the already-moved generation
    # pending for the next maintenance pass; availability recovery dominates
    # archive cleanup.
    assert (
        tmp_path / "service.log.lt05-pending"
    ).exists()


def test_crash_after_publish_before_pending_retire_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "service.log"

    newest = b"newest"
    old1 = b"old-1"
    old2 = b"old-2"
    old3 = b"old-3"

    path.write_bytes(newest)

    for generation, payload in {
        1: old1,
        2: old2,
        3: old3,
    }.items():
        with gzip.open(
            tmp_path / f"service.log.{generation}.gz",
            "wb",
        ) as handle:
            handle.write(payload)

    pending = tmp_path / "service.log.lt05-pending"
    published = (
        tmp_path / "service.log.lt05-archive-published"
    )

    class SimulatedCrash(BaseException):
        pass

    real_unlink = Path.unlink
    crashed = False

    def crash_on_pending_retire(
        target: Path,
        *args,
        **kwargs,
    ):
        nonlocal crashed

        if target == pending and not crashed:
            crashed = True
            raise SimulatedCrash(
                "post-publish pre-pending-retire crash"
            )

        return real_unlink(target, *args, **kwargs)

    maintenance = ExternalLogMaintenance()

    monkeypatch.setattr(
        Path,
        "unlink",
        crash_on_pending_retire,
    )

    with pytest.raises(SimulatedCrash):
        maintenance.run_once(
            policy(path, max_bytes=1, backups=3),
            FakeOwner(),
        )

    monkeypatch.setattr(
        Path,
        "unlink",
        real_unlink,
    )

    # Publication committed, but source retirement did not.
    assert pending.exists()
    assert published.exists()

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == newest
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == old1
    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == old2

    second = maintenance.run_once(
        policy(path, max_bytes=10**9, backups=3),
        FakeOwner(),
    )

    assert second.status is MaintenanceStatus.SUCCESS
    assert second.detail == "pending-recovered"

    # The already-published pending generation is retired, not republished.
    assert not pending.exists()
    assert not published.exists()

    assert read_gzip(
        tmp_path / "service.log.1.gz"
    ) == newest
    assert read_gzip(
        tmp_path / "service.log.2.gz"
    ) == old1
    assert read_gzip(
        tmp_path / "service.log.3.gz"
    ) == old2


def test_unresolved_pending_blocks_sibling_rotation_for_owner_group(
    tmp_path: Path,
) -> None:
    blocked = tmp_path / "blocked.log"
    fresh = tmp_path / "fresh.log"

    blocked.write_bytes(b"blocked-active")
    fresh_payload = b"fresh-needs-rotation" * 8
    fresh.write_bytes(fresh_payload)

    blocked_pending = (
        tmp_path / "blocked.log.lt05-pending"
    )
    blocked_pending.write_bytes(
        b"unresolved-older-generation"
    )

    class FailingPendingMaintenance(
        ExternalLogMaintenance
    ):
        def _archive_pending(
            self,
            item: ExternalLogPolicy,
        ) -> None:
            if item.path == blocked:
                raise OSError(
                    "injected-pending-recovery-failure"
                )
            super()._archive_pending(item)

    owner = FakeOwner()

    result = FailingPendingMaintenance().run_group(
        (
            policy(
                blocked,
                max_bytes=10**9,
                backups=3,
            ),
            policy(
                fresh,
                max_bytes=1,
                backups=3,
            ),
        ),
        owner,
    )

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert result.detail == "owner-group-pending-unresolved"

    by_path = dict(result.results)

    assert (
        by_path[blocked].status
        is MaintenanceStatus.FAILED_RECOVERED
    )
    assert not by_path[blocked].rotated

    assert by_path[fresh].status is MaintenanceStatus.NOOP
    assert not by_path[fresh].rotated
    assert (
        by_path[fresh].detail
        == "rotation-deferred:owner-group-pending-unresolved"
    )

    assert blocked_pending.exists()

    assert fresh.exists()
    assert fresh.read_bytes() == fresh_payload
    assert not (
        tmp_path / "fresh.log.lt05-pending"
    ).exists()
    assert not (
        tmp_path / "fresh.log.1.gz"
    ).exists()

    # No owner lifecycle mutation may begin.
    assert owner.stop_calls == 0
    assert owner.start_calls == 0
    assert owner.close_calls == 0
    assert owner.readback_calls == 0


def test_toolhive_owner_reuses_existing_lifecycle_and_q10(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        ToolHiveExternalLogOwner,
    )

    log = tmp_path / "toolhive.log"
    log.write_text("old")

    class Containment:
        def __init__(self) -> None:
            self.running = True
            self.stop_calls = 0
            self.start_calls = 0
            self.health_calls = 0

        def health(self) -> bool:
            self.health_calls += 1
            return self.running

        def stop(self) -> None:
            self.stop_calls += 1
            self.running = False

        def start(self) -> None:
            self.start_calls += 1
            self.running = True

    containment = Containment()
    open_new = False
    readbacks = 0

    def lsof(argv, **kwargs):
        if open_new:
            return subprocess.CompletedProcess(
                argv,
                0,
                "thv 123 user 1w REG toolhive.log\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 1, "", "")

    def real_readback() -> bool:
        nonlocal readbacks
        readbacks += 1
        return True

    owner = ToolHiveExternalLogOwner(
        containment=containment,
        log_paths=(log,),
        real_readback=real_readback,
        lsof_runner=lsof,
        sleep=lambda _: None,
        start_timeout=0,
    )

    assert owner.is_running()

    owner.stop()
    old_inode = owner._pre_stop_inodes[log]

    assert containment.stop_calls == 1
    assert owner.wait_log_closed(log)

    pending = tmp_path / "toolhive.log.lt05-pending"
    log.rename(pending)
    log.write_text("new")

    assert pending.stat().st_ino == old_inode
    assert log.stat().st_ino != old_inode

    open_new = True

    owner.start()

    assert containment.start_calls == 1
    assert owner.readback_ready()
    assert readbacks == 1
    assert owner._pre_stop_inodes == {}


def test_toolhive_owner_lsof_error_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ai_foundation.external_log_maintenance import (
        ToolHiveExternalLogOwner,
    )

    log = tmp_path / "toolhive.log"
    log.write_text("x")

    class Containment:
        def health(self) -> bool:
            return True

        def stop(self) -> None:
            pass

        def start(self) -> None:
            pass

    ticks = iter((0.0, 2.0))

    monkeypatch.setattr(
        "ai_foundation.external_log_maintenance.time.monotonic",
        lambda: next(ticks),
    )

    def lsof(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "lsof: injected error",
        )

    owner = ToolHiveExternalLogOwner(
        containment=Containment(),
        log_paths=(log,),
        real_readback=lambda: True,
        lsof_runner=lsof,
        sleep=lambda _: None,
        stop_timeout=1,
    )

    assert owner.wait_log_closed(log) is False


def test_toolhive_owner_rejects_unknown_log_path(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        ToolHiveExternalLogOwner,
    )

    log = tmp_path / "toolhive.log"
    other = tmp_path / "other.log"

    class Containment:
        def health(self) -> bool:
            return True

        def stop(self) -> None:
            pass

        def start(self) -> None:
            pass

    owner = ToolHiveExternalLogOwner(
        containment=Containment(),
        log_paths=(log,),
        real_readback=lambda: True,
    )

    assert owner.wait_log_closed(other) is False


def test_launchd_loaded_nonrunning_job_is_restoration_target(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    def runner(argv, **kwargs):
        assert argv[1] == "print"
        return subprocess.CompletedProcess(
            argv,
            0,
            "state = waiting\n",
            "",
        )

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=tmp_path / "service.plist",
        log_paths=(tmp_path / "service.log",),
        readback=lambda: True,
        uid=501,
        runner=runner,
    )

    assert owner.is_running() is True


def test_launchd_unloaded_job_is_not_restoration_target(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    def runner(argv, **kwargs):
        assert argv[1] == "print"
        return subprocess.CompletedProcess(
            argv,
            113,
            "",
            "Could not find service",
        )

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=tmp_path / "service.plist",
        log_paths=(tmp_path / "service.log",),
        readback=lambda: True,
        uid=501,
        runner=runner,
    )

    assert owner.is_running() is False


def test_launchd_owner_uses_bootout_fd_close_bootstrap_and_real_readback(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    plist = tmp_path / "service.plist"
    plist.write_text("plist")
    log = tmp_path / "service.log"
    log.write_text("x")

    calls = []
    prints = iter(
        (
            subprocess.CompletedProcess([], 0, "state = running\n", ""),
            subprocess.CompletedProcess([], 0, "state = running\n", ""),
        )
    )

    def runner(argv, **kwargs):
        calls.append(tuple(argv))
        if argv[1] == "print":
            return next(prints)
        return subprocess.CompletedProcess(argv, 0, "", "")

    lsof_calls = 0

    def lsof(argv, **kwargs):
        nonlocal lsof_calls
        lsof_calls += 1
        if lsof_calls == 1:
            return subprocess.CompletedProcess(
                argv, 0, "python 1 user 1w REG service.log\n", ""
            )
        return subprocess.CompletedProcess(argv, 1, "", "")

    readbacks = 0

    def readback():
        nonlocal readbacks
        readbacks += 1
        return True

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=plist,
        log_paths=(log,),
        readback=readback,
        uid=501,
        runner=runner,
        lsof_runner=lsof,
        sleep=lambda _: None,
        poll_interval=0,
    )

    assert owner.is_running()
    owner.stop()
    old_inode = owner._pre_stop_inodes[log]
    assert old_inode == log.stat().st_ino
    assert owner.wait_log_closed(log)

    # Model the real LT05 boundary: rotation retires the old active path,
    # then launchd bootstrap opens a fresh active file.
    retired = tmp_path / "service.log.lt05-pending"
    log.rename(retired)
    log.write_text("new-active")
    assert log.stat().st_ino != old_inode

    # wait_log_closed consumed calls 1 and 2. The post-bootstrap active
    # descriptor must now be visibly open for Q10 readback to pass.
    lsof_calls = 2

    def reopened_lsof(argv, **kwargs):
        nonlocal lsof_calls
        lsof_calls += 1
        return subprocess.CompletedProcess(
            argv,
            0,
            "python 2 user 1w REG service.log\\n",
            "",
        )

    owner.lsof_runner = reopened_lsof

    owner.start()
    assert owner.readback_ready()

    assert (
        "/bin/launchctl",
        "bootout",
        "gui/501",
        str(plist),
    ) in calls
    assert (
        "/bin/launchctl",
        "bootstrap",
        "gui/501",
        str(plist),
    ) in calls
    # Two lsof calls prove the old descriptor closed; the third proves
    # the fresh post-bootstrap active inode is actually open.
    assert lsof_calls == 3
    assert readbacks == 1


def test_launchd_owner_lsof_error_is_not_close_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    log = tmp_path / "service.log"
    ticks = iter((0.0, 2.0))

    monkeypatch.setattr(
        "ai_foundation.external_log_maintenance.time.monotonic",
        lambda: next(ticks),
    )

    def lsof(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "lsof: status error: injected",
        )

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=tmp_path / "service.plist",
        log_paths=(log,),
        readback=lambda: True,
        uid=501,
        lsof_runner=lsof,
        sleep=lambda _: None,
        stop_timeout=1,
    )

    assert owner.wait_log_closed(log) is False


def test_launchd_owner_readback_requires_new_open_inode(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    plist = tmp_path / "service.plist"
    log = tmp_path / "service.log"
    log.write_text("old")

    def runner(argv, **kwargs):
        if argv[1] == "print":
            return subprocess.CompletedProcess(
                argv, 0, "state = running\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    lsof_open = False

    def lsof(argv, **kwargs):
        if lsof_open:
            return subprocess.CompletedProcess(
                argv,
                0,
                "python 123 user 1w REG service.log\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 1, "", "")

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=plist,
        log_paths=(log,),
        readback=lambda: True,
        uid=501,
        runner=runner,
        lsof_runner=lsof,
        sleep=lambda _: None,
        start_timeout=0,
    )

    owner.stop()
    old_inode = owner._pre_stop_inodes[log]
    assert old_inode == log.stat().st_ino

    # Same active inode is not restart/reopen proof.
    assert owner.readback_ready() is False

    # Simulate rotation + bootstrap creating a fresh active path while
    # retaining the old inode at the pending path, exactly like LT05.
    pending = tmp_path / "service.log.lt05-pending"
    log.rename(pending)
    log.write_text("new")
    assert pending.stat().st_ino == old_inode
    assert log.stat().st_ino != old_inode

    lsof_open = True
    assert owner.readback_ready() is True
    assert owner._pre_stop_inodes == {}


def test_launchd_owner_fd_close_timeout_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    plist = tmp_path / "service.plist"
    log = tmp_path / "service.log"

    ticks = iter((0.0, 2.0))

    monkeypatch.setattr(
        "ai_foundation.external_log_maintenance.time.monotonic",
        lambda: next(ticks),
    )

    def lsof(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            "python 1 user 1w REG service.log\n",
            "",
        )

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=plist,
        log_paths=(log,),
        readback=lambda: True,
        uid=501,
        lsof_runner=lsof,
        sleep=lambda _: None,
        stop_timeout=1,
    )

    assert owner.wait_log_closed(log) is False


def test_launchd_owner_bootout_and_bootstrap_fail_explicitly(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    plist = tmp_path / "service.plist"
    log = tmp_path / "service.log"
    failing = "bootout"

    def runner(argv, **kwargs):
        if argv[1] == failing:
            return subprocess.CompletedProcess(
                argv, 5, "", "injected"
            )
        return subprocess.CompletedProcess(
            argv, 0, "state = running\n", ""
        )

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=plist,
        log_paths=(log,),
        readback=lambda: True,
        uid=501,
        runner=runner,
    )

    with pytest.raises(RuntimeError):
        owner.stop()

    failing = "bootstrap"

    with pytest.raises(RuntimeError):
        owner.start()


def test_external_log_campaign_holds_one_cross_process_lease(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceCampaign,
        ExternalLogOwnerGroup,
        ExternalLogPolicy,
        GroupMaintenanceResult,
        MaintenanceStatus,
    )

    class Maintenance:
        def __init__(self):
            self.calls = []

        def run_group(self, policies, owner):
            self.calls.append((policies, owner))
            return GroupMaintenanceResult(
                MaintenanceStatus.NOOP,
                (),
                False,
                "below-threshold",
            )

    class Owner:
        pass

    maintenance = Maintenance()
    owner = Owner()
    policy = ExternalLogPolicy(tmp_path / "service.log", 1024)

    campaign = ExternalLogMaintenanceCampaign(
        maintenance=maintenance,
        lease_path=tmp_path / "campaign.lock",
        groups=(
            ExternalLogOwnerGroup(
                "service",
                (policy,),
                owner,
            ),
        ),
    )

    # Hold the exact campaign lease externally.
    from ai_foundation.external_log_maintenance import (
        ExternalLogMaintenanceLease,
    )

    with ExternalLogMaintenanceLease(
        tmp_path / "campaign.lock"
    ).acquire() as acquired:
        assert acquired
        blocked = campaign.run_once()

    assert isinstance(blocked, CampaignResult)
    assert blocked.status is MaintenanceStatus.NOOP
    assert blocked.detail == "maintenance-already-running"
    assert maintenance.calls == []

    completed = campaign.run_once()
    assert completed.status is MaintenanceStatus.NOOP
    assert completed.detail == "campaign-complete"
    assert len(maintenance.calls) == 1


def test_external_log_campaign_stops_after_unrecovered_owner(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        ExternalLogMaintenanceCampaign,
        ExternalLogOwnerGroup,
        ExternalLogPolicy,
        GroupMaintenanceResult,
        MaintenanceStatus,
    )

    class Maintenance:
        def __init__(self):
            self.calls = []

        def run_group(self, policies, owner):
            self.calls.append(owner)
            if owner == "broken":
                return GroupMaintenanceResult(
                    MaintenanceStatus.FAILED_UNRECOVERED,
                    (),
                    False,
                    "owner-recovery-failed",
                )
            return GroupMaintenanceResult(
                MaintenanceStatus.SUCCESS,
                (),
                True,
                "rotated",
            )

    campaign = ExternalLogMaintenanceCampaign(
        maintenance=Maintenance(),
        lease_path=tmp_path / "campaign.lock",
        groups=(
            ExternalLogOwnerGroup(
                "first",
                (ExternalLogPolicy(tmp_path / "first.log", 1),),
                "broken",
            ),
            ExternalLogOwnerGroup(
                "second",
                (ExternalLogPolicy(tmp_path / "second.log", 1),),
                "must-not-run",
            ),
        ),
    )

    result = campaign.run_once()

    assert result.status is MaintenanceStatus.FAILED_UNRECOVERED
    assert result.detail == "owner-unrecovered:first"
    assert campaign.maintenance.calls == ["broken"]


def test_external_log_campaign_continues_after_recovered_failure(
    tmp_path: Path,
) -> None:
    from ai_foundation.external_log_maintenance import (
        ExternalLogMaintenanceCampaign,
        ExternalLogOwnerGroup,
        ExternalLogPolicy,
        GroupMaintenanceResult,
        MaintenanceStatus,
    )

    class Maintenance:
        def __init__(self):
            self.calls = []

        def run_group(self, policies, owner):
            self.calls.append(owner)
            if owner == "recovered":
                return GroupMaintenanceResult(
                    MaintenanceStatus.FAILED_RECOVERED,
                    (),
                    True,
                    "rotation-failed-owner-restored",
                )
            return GroupMaintenanceResult(
                MaintenanceStatus.NOOP,
                (),
                False,
                "below-threshold",
            )

    campaign = ExternalLogMaintenanceCampaign(
        maintenance=Maintenance(),
        lease_path=tmp_path / "campaign.lock",
        groups=(
            ExternalLogOwnerGroup(
                "first",
                (ExternalLogPolicy(tmp_path / "first.log", 1),),
                "recovered",
            ),
            ExternalLogOwnerGroup(
                "second",
                (ExternalLogPolicy(tmp_path / "second.log", 1),),
                "healthy",
            ),
        ),
    )

    result = campaign.run_once()

    assert result.status is MaintenanceStatus.FAILED_RECOVERED
    assert campaign.maintenance.calls == ["recovered", "healthy"]


def test_external_log_campaign_rejects_duplicate_group_names(
    tmp_path: Path,
) -> None:
    import pytest

    from ai_foundation.external_log_maintenance import (
        ExternalLogMaintenance,
        ExternalLogMaintenanceCampaign,
        ExternalLogOwnerGroup,
        ExternalLogPolicy,
    )

    class Owner:
        pass

    group = ExternalLogOwnerGroup(
        "same",
        (ExternalLogPolicy(tmp_path / "service.log", 1),),
        Owner(),
    )

    with pytest.raises(
        ValueError,
        match="group names must be unique",
    ):
        ExternalLogMaintenanceCampaign(
            maintenance=ExternalLogMaintenance(),
            lease_path=tmp_path / "campaign.lock",
            groups=(group, group),
        )


def test_launchd_owner_partial_move_accepts_unmoved_open_sibling(
    tmp_path: Path,
) -> None:
    import subprocess

    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    moved = tmp_path / "stdout.log"
    unmoved = tmp_path / "stderr.log"
    plist = tmp_path / "service.plist"

    moved.write_text("stdout-old")
    unmoved.write_text("stderr-old")

    def runner(argv, **kwargs):
        if argv[1] == "print":
            return subprocess.CompletedProcess(
                argv, 0, "state = running\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    opened = False

    def lsof(argv, **kwargs):
        if opened:
            return subprocess.CompletedProcess(
                argv,
                0,
                "python 123 user 1w REG log\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 1, "", "")

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=plist,
        log_paths=(moved, unmoved),
        readback=lambda: True,
        uid=501,
        runner=runner,
        lsof_runner=lsof,
        sleep=lambda _: None,
        start_timeout=0,
    )

    owner.stop()

    moved_old = owner._pre_stop_inodes[moved]
    unmoved_old = owner._pre_stop_inodes[unmoved]

    assert owner.wait_log_closed(moved)
    assert owner.wait_log_closed(unmoved)

    pending = tmp_path / "stdout.log.lt05-pending"
    moved.rename(pending)

    # This models failure of the second active->pending move.
    assert not moved.exists()
    assert unmoved.exists()
    assert unmoved.stat().st_ino == unmoved_old

    owner.start()

    # start() must record only the path actually absent/moved.
    assert owner._require_new_inode == {moved}

    moved.write_text("stdout-new")
    assert moved.stat().st_ino != moved_old
    assert unmoved.stat().st_ino == unmoved_old

    opened = True

    # Q10: moved path has a new inode; unmoved sibling is merely reopened.
    assert owner.readback_ready()
    assert owner._pre_stop_inodes == {}
    assert owner._require_new_inode == set()


def test_toolhive_owner_partial_move_accepts_unmoved_open_sibling(
    tmp_path: Path,
) -> None:
    import subprocess

    from ai_foundation.external_log_maintenance import (
        ToolHiveExternalLogOwner,
    )

    moved = tmp_path / "stdout.log"
    unmoved = tmp_path / "stderr.log"

    moved.write_text("stdout-old")
    unmoved.write_text("stderr-old")

    class Containment:
        def __init__(self) -> None:
            self.running = True

        def health(self) -> bool:
            return self.running

        def stop(self) -> None:
            self.running = False

        def start(self) -> None:
            self.running = True

    opened = False

    def lsof(argv, **kwargs):
        if opened:
            return subprocess.CompletedProcess(
                argv,
                0,
                "thv 123 user 1w REG log\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 1, "", "")

    owner = ToolHiveExternalLogOwner(
        containment=Containment(),
        log_paths=(moved, unmoved),
        real_readback=lambda: True,
        lsof_runner=lsof,
        sleep=lambda _: None,
        start_timeout=0,
    )

    owner.stop()

    moved_old = owner._pre_stop_inodes[moved]
    unmoved_old = owner._pre_stop_inodes[unmoved]

    assert owner.wait_log_closed(moved)
    assert owner.wait_log_closed(unmoved)

    pending = tmp_path / "stdout.log.lt05-pending"
    moved.rename(pending)

    assert not moved.exists()
    assert unmoved.exists()
    assert unmoved.stat().st_ino == unmoved_old

    owner.start()

    assert owner._require_new_inode == {moved}

    moved.write_text("stdout-new")
    assert moved.stat().st_ino != moved_old
    assert unmoved.stat().st_ino == unmoved_old

    opened = True

    assert owner.readback_ready()
    assert owner._pre_stop_inodes == {}
    assert owner._require_new_inode == set()


def test_launchd_owner_normal_rotation_still_rejects_same_inode(
    tmp_path: Path,
) -> None:
    import subprocess

    from ai_foundation.external_log_maintenance import (
        LaunchdExternalLogOwner,
    )

    log = tmp_path / "service.log"
    plist = tmp_path / "service.plist"
    log.write_text("old")

    def runner(argv, **kwargs):
        if argv[1] == "print":
            return subprocess.CompletedProcess(
                argv, 0, "state = running\n", ""
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    def lsof(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            "python 123 user 1w REG service.log\n",
            "",
        )

    owner = LaunchdExternalLogOwner(
        label="dev.example.service",
        plist=plist,
        log_paths=(log,),
        readback=lambda: True,
        uid=501,
        runner=runner,
        lsof_runner=lsof,
        sleep=lambda _: None,
        start_timeout=0,
    )

    owner.stop()
    old_inode = owner._pre_stop_inodes[log]

    # Core moved active away.
    pending = tmp_path / "service.log.lt05-pending"
    log.rename(pending)
    assert not log.exists()

    owner.start()
    assert owner._require_new_inode == {log}

    # Deliberately restore the same inode to active. This must not count as
    # reopen proof for a path that was actually rotated.
    pending.rename(log)
    assert log.stat().st_ino == old_inode

    assert owner.readback_ready() is False

def test_production_external_log_campaign_composes_five_owner_groups(tmp_path):
    from ai_foundation.external_log_maintenance import (
        build_production_external_log_campaign,
    )

    home = tmp_path / "home"
    data = home / "Library/Application Support/AI-Foundation"
    repo = home / "Develop/AI-Foundation"

    made = []

    class Owner:
        def __init__(self, **kw):
            self.kw = kw
            made.append(kw)

        def is_running(self):
            return False

        def stop(self):
            raise AssertionError("composition must not mutate owner")

        def wait_log_closed(self, path):
            raise AssertionError("composition must not mutate owner")

        def start(self):
            raise AssertionError("composition must not mutate owner")

        def readback_ready(self):
            raise AssertionError("composition must not execute readback")

    campaign = build_production_external_log_campaign(
        data_dir=data,
        repo_root=repo,
        home=home,
        launchd_owner_factory=Owner,
        toolhive_owner_factory=Owner,
        toolhive_lifecycle_factory=lambda name: ("lifecycle", name),
        toolhive_readback_factory=lambda name: lambda: True,
        operator_readback=lambda: True,
        chat_readback=lambda: True,
        llama_readback=lambda: True,
    )

    assert [g.name for g in campaign.groups] == [
        "operator",
        "chat-gateway",
        "llama-swap",
        "ai-foundation-fs",
        "ai-foundation-repo",
    ]

    by_name = {g.name: g for g in campaign.groups}

    assert len(by_name["operator"].policies) == 2
    assert len(by_name["chat-gateway"].policies) == 2
    assert len(by_name["llama-swap"].policies) == 1
    assert len(by_name["ai-foundation-fs"].policies) == 1
    assert len(by_name["ai-foundation-repo"].policies) == 1

    assert by_name["llama-swap"].policies[0].max_bytes == 256 * 1024 * 1024

    for name in ("operator", "chat-gateway", "ai-foundation-fs", "ai-foundation-repo"):
        assert all(p.max_bytes == 64 * 1024 * 1024 for p in by_name[name].policies)

    assert all(p.backup_count == 3 for g in campaign.groups for p in g.policies)

    assert campaign.lease_path == data / "external-log-maintenance.lock"

    # Construction only: no owner lifecycle/readback operation happened.
    assert len(made) == 5


def test_external_log_maintenance_launchd_job_is_hourly_one_shot():
    import plistlib
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    plist = (
        repo
        / "ops/launchd"
        / "dev.quest7070.ai-foundation.external-log-maintenance.plist"
    )

    with plist.open("rb") as f:
        row = plistlib.load(f)

    assert row["Label"] == (
        "dev.quest7070.ai-foundation.external-log-maintenance"
    )
    assert row["StartInterval"] == 3600

    # Maintenance is a bounded campaign, not a resident daemon.
    assert "KeepAlive" not in row
    assert "RunAtLoad" not in row

    args = row["ProgramArguments"]

    assert args[0] == "__REPO_ROOT__/.venv/bin/python"
    assert args[1] == "__REPO_ROOT__/scripts/external_log_maintenance.py"
    assert args[2] == "--config"
    assert args[3] == "__CONFIG_PATH__"
    assert args[4:] == ["--repo-root", "__REPO_ROOT__"]
    assert row["WorkingDirectory"] == "__REPO_ROOT__"

    # The maintenance scheduler must not create its own unbounded
    # persistent append-log surface. Durable machine-readable outcome
    # evidence is external-log-maintenance.json.
    assert row["StandardOutPath"] == "/dev/null"
    assert row["StandardErrorPath"] == "/dev/null"


def test_external_log_state_store_is_atomic_single_record(tmp_path):
    import json

    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceStateStore,
        MaintenanceStatus,
    )

    path = tmp_path / "external-log-maintenance.json"
    store = ExternalLogMaintenanceStateStore(path)

    result = CampaignResult(
        status=MaintenanceStatus.NOOP,
        groups=(),
        detail="campaign-complete",
    )

    store.save(result, checked_at=123.0)

    row = json.loads(path.read_text())
    assert row == {
        "checked_at": 123.0,
        "detail": "campaign-complete",
        "groups": [],
        "status": "NOOP",
    }
    assert not path.with_suffix(".json.tmp").exists()


def test_external_log_state_store_replaces_previous_record(tmp_path):
    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceStateStore,
        MaintenanceStatus,
    )

    path = tmp_path / "external-log-maintenance.json"
    store = ExternalLogMaintenanceStateStore(path)

    store.save(
        CampaignResult(
            MaintenanceStatus.NOOP,
            (),
            "first",
        ),
        checked_at=1.0,
    )

    store.save(
        CampaignResult(
            MaintenanceStatus.FAILED_RECOVERED,
            (),
            "second",
        ),
        checked_at=2.0,
    )

    row = store.load()

    assert row["checked_at"] == 2.0
    assert row["status"] == "FAILED_RECOVERED"
    assert row["detail"] == "second"


def test_external_log_state_store_does_not_touch_long_term_health(tmp_path):
    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceStateStore,
        MaintenanceStatus,
    )

    health = tmp_path / "long-term-health.json"
    health.write_text('{"sentinel":"unchanged"}\n')

    store = ExternalLogMaintenanceStateStore(
        tmp_path / "external-log-maintenance.json"
    )
    store.save(
        CampaignResult(
            MaintenanceStatus.NOOP,
            (),
            "campaign-complete",
        ),
        checked_at=1.0,
    )

    assert health.read_text() == '{"sentinel":"unchanged"}\n'


def test_external_log_notice_is_absent_for_success_state(tmp_path):
    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceStateStore,
        MaintenanceStatus,
        external_log_maintenance_notice,
    )

    store = ExternalLogMaintenanceStateStore(
        tmp_path / "external-log-maintenance.json"
    )

    for status in (
        MaintenanceStatus.NOOP,
        MaintenanceStatus.SUCCESS,
    ):
        store.save(
            CampaignResult(
                status=status,
                groups=(),
                detail="campaign-complete",
            ),
            checked_at=123.0,
        )
        assert external_log_maintenance_notice(store) == ()


def test_external_log_recovered_failure_projects_existing_notice(tmp_path):
    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceStateStore,
        GroupMaintenanceResult,
        MaintenanceStatus,
        external_log_maintenance_notice,
    )

    store = ExternalLogMaintenanceStateStore(
        tmp_path / "external-log-maintenance.json"
    )

    group = GroupMaintenanceResult(
        status=MaintenanceStatus.FAILED_RECOVERED,
        results=(),
        recovered=True,
        detail="archive-failed-owner-restored",
    )

    store.save(
        CampaignResult(
            status=MaintenanceStatus.FAILED_RECOVERED,
            groups=(("llama-swap", group),),
            detail="campaign-complete",
        ),
        checked_at=123.0,
    )

    notices = external_log_maintenance_notice(store)

    assert len(notices) == 1
    notice = notices[0]

    assert notice.level == 3
    assert notice.kind == "system"
    assert notice.subject == "external-log-maintenance"
    assert notice.status == "FAILED"
    assert notice.actionable is False
    assert notice.input_required is False
    assert notice.updated_at == 123.0
    assert "llama-swap" in notice.detail_ja


def test_external_log_unrecovered_failure_projects_same_stable_identity(
    tmp_path,
):
    from ai_foundation.external_log_maintenance import (
        CampaignResult,
        ExternalLogMaintenanceStateStore,
        MaintenanceStatus,
        external_log_maintenance_notice,
    )

    store = ExternalLogMaintenanceStateStore(
        tmp_path / "external-log-maintenance.json"
    )

    store.save(
        CampaignResult(
            status=MaintenanceStatus.FAILED_UNRECOVERED,
            groups=(),
            detail="owner-recovery-failed",
        ),
        checked_at=456.0,
    )

    notice = external_log_maintenance_notice(store)[0]

    assert notice.subject == "external-log-maintenance"
    assert notice.status == "FAILED"
    assert notice.updated_at == 456.0
    assert "incomplete" in notice.summary_ja


def test_external_log_notice_tolerates_absent_or_invalid_state(tmp_path):
    from ai_foundation.external_log_maintenance import (
        ExternalLogMaintenanceStateStore,
        external_log_maintenance_notice,
    )

    path = tmp_path / "external-log-maintenance.json"
    store = ExternalLogMaintenanceStateStore(path)

    assert external_log_maintenance_notice(store) == ()

    path.write_text("{broken")
    assert external_log_maintenance_notice(store) == ()
