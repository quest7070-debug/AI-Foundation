from __future__ import annotations

import fcntl
import gzip
import os
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol


class MaintenanceStatus(str, Enum):
    NOOP = "NOOP"
    SUCCESS = "SUCCESS"
    FAILED_RECOVERED = "FAILED_RECOVERED"
    FAILED_UNRECOVERED = "FAILED_UNRECOVERED"


@dataclass(frozen=True)
class ExternalLogPolicy:
    path: Path
    max_bytes: int
    backup_count: int = 3

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.backup_count < 1:
            raise ValueError("backup_count must be at least 1")


@dataclass(frozen=True)
class MaintenanceResult:
    status: MaintenanceStatus
    rotated: bool
    recovered: bool
    detail: str = ""


@dataclass(frozen=True)
class GroupMaintenanceResult:
    status: MaintenanceStatus
    results: tuple[tuple[Path, MaintenanceResult], ...]
    recovered: bool
    detail: str = ""

    @property
    def rotated(self) -> bool:
        return any(result.rotated for _, result in self.results)


class ExternalLogOwner(Protocol):
    """
    Service-specific lifecycle authority.

    Rotation mechanics do not know whether the owner is launchd, ToolHive,
    llama-swap, or another external process.
    """

    def is_running(self) -> bool:
        ...

    def stop(self) -> None:
        ...

    def wait_log_closed(self, path: Path) -> bool:
        ...

    def start(self) -> None:
        ...

    def readback_ready(self) -> bool:
        ...


class ExternalLogMaintenanceLease:
    """
    Non-blocking cross-process lease for one external-log maintenance campaign.

    The caller owns placement of the lock file. Production runners should place
    it under the canonical Foundation data directory. The maintenance primitive
    itself remains owner-neutral and host-layout-neutral.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = Path(lock_path)

    @contextmanager
    def acquire(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.lock_path, "a+b") as lock:
            try:
                fcntl.flock(
                    lock.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError:
                yield False
                return

            try:
                yield True
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class ExternalLogMaintenance:
    """
    Owner-neutral external-log maintenance.

    Availability contract
    ---------------------
    For a running owner, service downtime contains only:

        stop
        -> descriptor-close proof
        -> active log renamed to fixed pending path
        -> start
        -> real owner readback

    Compression and generation retention happen only after service recovery.

    Crash contract
    --------------
    A fixed ``.lt05-pending`` path is the only pre-archive intermediate state.
    If it exists on a later invocation it is archived before a new rotation is
    considered.  It is never silently discarded.

    This object owns rotation mechanics only.  It does not own service
    lifecycle policy, scheduling, health observation, or notification.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def _pending(path: Path) -> Path:
        return path.with_name(f"{path.name}.lt05-pending")

    @staticmethod
    def _generation(path: Path, generation: int) -> Path:
        return path.with_name(f"{path.name}.{generation}.gz")

    def run_once(
        self,
        policy: ExternalLogPolicy,
        owner: ExternalLogOwner,
    ) -> MaintenanceResult:
        """Single-path compatibility wrapper over the owner-group primitive."""
        group = self.run_group((policy,), owner)

        if len(group.results) == 1:
            return group.results[0][1]

        # Group-level suppression occurs before any path is evaluated, so
        # there is intentionally no per-path result. Preserve the historical
        # single-path run_once() contract instead of turning contention into
        # an exception.
        if (
            not group.results
            and group.status is MaintenanceStatus.NOOP
            and group.detail == "maintenance-already-running"
        ):
            return MaintenanceResult(
                MaintenanceStatus.NOOP,
                rotated=False,
                recovered=False,
                detail="maintenance-already-running",
            )

        raise RuntimeError("single-path-group-result-invalid")

    def run_group(
        self,
        policies: tuple[ExternalLogPolicy, ...],
        owner: ExternalLogOwner,
    ) -> GroupMaintenanceResult:
        """
        Maintain all external logs owned by one service lifecycle.

        A running owner is stopped/start/read back at most once per invocation,
        regardless of how many owned paths require rotation.
        """
        if not self._lock.acquire(blocking=False):
            return GroupMaintenanceResult(
                MaintenanceStatus.NOOP,
                results=(),
                recovered=False,
                detail="maintenance-already-running",
            )

        try:
            return self._run_group_locked(policies, owner)
        finally:
            self._lock.release()

    def _run_group_locked(
        self,
        policies: tuple[ExternalLogPolicy, ...],
        owner: ExternalLogOwner,
    ) -> GroupMaintenanceResult:
        # One physical path must have exactly one policy in an owner group.
        unique: dict[Path, ExternalLogPolicy] = {}

        for policy in policies:
            existing = unique.get(policy.path)
            if existing is None:
                unique[policy.path] = policy
                continue

            if existing != policy:
                raise ValueError(
                    f"conflicting policies for external log: {policy.path}"
                )

        ordered = tuple(unique.values())

        if not ordered:
            return GroupMaintenanceResult(
                MaintenanceStatus.NOOP,
                results=(),
                recovered=False,
                detail="no-policies",
            )

        results: dict[Path, MaintenanceResult] = {}
        rotate: list[ExternalLogPolicy] = []

        # Existing crash residue has owner-group priority. Recover pending
        # state for every path where possible, but do not create a new pending
        # generation for any sibling while one remains unresolved.
        pending_recovery_failed = False

        # Resolve archive/GC state before deciding whether owner downtime is
        # needed. Existing pending authority is archived without stopping the
        # already-recovered owner.
        for policy in ordered:
            path = policy.path
            pending = self._pending(path)

            if not pending.exists():
                self._collect_archive_published(path)

            if pending.exists():
                try:
                    self._archive_pending(policy)
                except Exception as exc:
                    results[path] = MaintenanceResult(
                        MaintenanceStatus.FAILED_RECOVERED,
                        rotated=False,
                        recovered=True,
                        detail=(
                            "pending-archive-failed:"
                            f"{type(exc).__name__}:{exc}"
                        ),
                    )
                    pending_recovery_failed = True
                    continue

                results[path] = MaintenanceResult(
                    MaintenanceStatus.SUCCESS,
                    rotated=False,
                    recovered=True,
                    detail="pending-recovered",
                )
                continue

            try:
                size = path.stat().st_size
            except FileNotFoundError:
                results[path] = MaintenanceResult(
                    MaintenanceStatus.NOOP,
                    rotated=False,
                    recovered=False,
                    detail="log-missing",
                )
                continue

            if size < policy.max_bytes:
                results[path] = MaintenanceResult(
                    MaintenanceStatus.NOOP,
                    rotated=False,
                    recovered=False,
                    detail="below-threshold",
                )
                continue

            rotate.append(policy)

        if not rotate:
            values = tuple(
                (policy.path, results[policy.path])
                for policy in ordered
            )
            status = (
                MaintenanceStatus.FAILED_RECOVERED
                if any(
                    result.status is MaintenanceStatus.FAILED_RECOVERED
                    for _, result in values
                )
                else (
                    MaintenanceStatus.SUCCESS
                    if any(
                        result.status is MaintenanceStatus.SUCCESS
                        for _, result in values
                    )
                    else MaintenanceStatus.NOOP
                )
            )
            return GroupMaintenanceResult(
                status,
                results=values,
                recovered=all(result.recovered for _, result in values),
                detail="no-owner-rotation-required",
            )

        if pending_recovery_failed:
            # All paths have completed preflight.  Existing pending recovery
            # has priority over starting any new owner downtime/rotation.
            for policy in rotate:
                results[policy.path] = MaintenanceResult(
                    MaintenanceStatus.NOOP,
                    rotated=False,
                    recovered=False,
                    detail=(
                        "rotation-deferred:"
                        "owner-group-pending-unresolved"
                    ),
                )

            values = tuple(
                (policy.path, results[policy.path])
                for policy in ordered
            )

            return GroupMaintenanceResult(
                MaintenanceStatus.FAILED_RECOVERED,
                results=values,
                recovered=True,
                detail="owner-group-pending-unresolved",
            )

        was_running = owner.is_running()
        stop_completed = False
        moved: set[Path] = set()

        try:
            if was_running:
                owner.stop()
                stop_completed = True

            # All descriptors must be proven closed before the first active
            # path is mutated. This prevents a partially rotated owner merely
            # because a later descriptor was still open.
            for policy in rotate:
                if not owner.wait_log_closed(policy.path):
                    raise RuntimeError(
                        f"owner-log-descriptor-remained-open:{policy.path}"
                    )

            for policy in rotate:
                path = policy.path
                os.replace(path, self._pending(path))
                moved.add(path)

            if was_running:
                owner.start()
                stop_completed = False

                if not owner.readback_ready():
                    raise RuntimeError("owner-readback-failed")

        except Exception as exc:
            recovered = self._recover_owner_once(
                owner=owner,
                was_running=was_running,
                stop_completed=stop_completed,
            )

            for policy in rotate:
                path = policy.path
                results[path] = MaintenanceResult(
                    (
                        MaintenanceStatus.FAILED_RECOVERED
                        if recovered
                        else MaintenanceStatus.FAILED_UNRECOVERED
                    ),
                    rotated=path in moved,
                    recovered=recovered,
                    detail=f"{type(exc).__name__}:{exc}",
                )

            values = tuple(
                (policy.path, results[policy.path])
                for policy in ordered
            )

            return GroupMaintenanceResult(
                (
                    MaintenanceStatus.FAILED_RECOVERED
                    if recovered
                    else MaintenanceStatus.FAILED_UNRECOVERED
                ),
                results=values,
                recovered=recovered,
                detail=f"{type(exc).__name__}:{exc}",
            )

        # Availability has been restored. Archive each pending path using the
        # already-proven single-path archive transaction.
        for policy in rotate:
            path = policy.path

            try:
                self._archive_pending(policy)
            except Exception as exc:
                results[path] = MaintenanceResult(
                    MaintenanceStatus.FAILED_RECOVERED,
                    rotated=True,
                    recovered=True,
                    detail=(
                        "post-recovery-archive-failed:"
                        f"{type(exc).__name__}:{exc}"
                    ),
                )
            else:
                results[path] = MaintenanceResult(
                    MaintenanceStatus.SUCCESS,
                    rotated=True,
                    recovered=True,
                    detail="rotated",
                )

        values = tuple(
            (policy.path, results[policy.path])
            for policy in ordered
        )

        status = (
            MaintenanceStatus.FAILED_RECOVERED
            if any(
                result.status is MaintenanceStatus.FAILED_RECOVERED
                for _, result in values
            )
            else MaintenanceStatus.SUCCESS
        )

        return GroupMaintenanceResult(
            status,
            results=values,
            recovered=True,
            detail="owner-group-maintained",
        )

    @staticmethod
    def _recover_owner_once(
        *,
        owner: ExternalLogOwner,
        was_running: bool,
        stop_completed: bool,
    ) -> bool:
        """
        One bounded recovery attempt.

        A pre-maintenance stopped owner stays stopped.

        For a previously running owner:

        * if the normal start did not complete, perform exactly one recovery
          start followed by real readback;
        * if the normal start completed but its readback failed, perform
          exactly one normal owner restart (stop -> start) followed by real
          readback.

        No recovery branch loops or recursively retries.
        """
        if not was_running:
            return True

        try:
            if stop_completed:
                owner.start()
            else:
                owner.stop()
                owner.start()

            return owner.readback_ready()
        except Exception:
            return False

    def _archive_pending(self, policy: ExternalLogPolicy) -> None:
        path = policy.path
        pending = self._pending(path)
        published = self._archive_published_dir(path)

        if not pending.exists():
            self._collect_archive_published(path)
            return

        # Publication committed before a crash, but pending retirement did
        # not.  The marker proves these bytes MUST NOT be published again.
        if published.exists():
            pending.unlink()
            self._collect_archive_published(path)
            return

        compressed_tmp = path.with_name(
            f"{path.name}.lt05-compressing"
        )

        if compressed_tmp.exists():
            # A previous compression never published. It is derived state;
            # pending remains authoritative.
            compressed_tmp.unlink()

        try:
            with pending.open("rb") as source, gzip.open(
                compressed_tmp,
                "wb",
            ) as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
        except Exception:
            compressed_tmp.unlink(missing_ok=True)
            raise

        self._publish_compressed(
            policy=policy,
            compressed_tmp=compressed_tmp,
        )

        # Publication commit is now represented by the published marker.
        # Retire pending only after that atomic commit proof exists.
        pending.unlink()

        # With pending gone the marker is no longer authority.
        self._collect_archive_published(path)

    @staticmethod
    def _archive_txn_dir(path: Path) -> Path:
        return path.with_name(f"{path.name}.lt05-archive-txn")

    @staticmethod
    def _archive_published_dir(path: Path) -> Path:
        return path.with_name(
            f"{path.name}.lt05-archive-published"
        )

    def _collect_archive_published(self, path: Path) -> bool:
        """
        Retire a publication marker only after pending is gone.

        pending + published is a committed-but-not-retired transaction and
        published must remain authoritative until pending is removed.
        """
        published = self._archive_published_dir(path)

        if not published.exists():
            return True

        if self._pending(path).exists():
            return False

        try:
            shutil.rmtree(published)
        except Exception:
            return False

        return not published.exists()

    def _publish_compressed(
        self,
        *,
        policy: ExternalLogPolicy,
        compressed_tmp: Path,
    ) -> None:
        """
        Publish pending compression from a restartable archive transaction.

        Before STAGED exists, existing generations are only being moved into
        the transaction directory.  No new generation is published.

        After STAGED exists, that directory is the immutable baseline for the
        old generation set.  Publication can therefore be repeated after a
        crash without interpreting partially published root generations.

        The authoritative pending log is removed by _archive_pending() only
        after this transaction has fully published and cleaned up.
        """
        path = policy.path
        txn = self._archive_txn_dir(path)
        published = self._archive_published_dir(path)
        staged_marker = txn / "STAGED"

        # _archive_pending handles pending + published without entering a new
        # publication.  A marker reaching this function therefore must be
        # retired state from an already-removed pending source.
        if published.exists():
            if self._pending(path).exists():
                raise RuntimeError(
                    "publication-already-committed"
                )

            if not self._collect_archive_published(path):
                raise RuntimeError(
                    "post-publication-marker-remains"
                )

        txn.mkdir(mode=0o700, exist_ok=True)

        if not staged_marker.exists():
            # Staging is restartable because publication cannot begin before
            # STAGED exists.  A generation already inside txn was moved by an
            # earlier interrupted staging attempt.
            for generation in range(1, policy.backup_count + 1):
                source = self._generation(path, generation)
                staged = txn / f"{generation}.gz"

                if staged.exists():
                    continue

                if source.exists():
                    os.replace(source, staged)

            marker_tmp = txn / "STAGED.tmp"
            marker_tmp.write_bytes(b"staged\n")
            os.replace(marker_tmp, staged_marker)

        # From this point txn is the immutable old-generation baseline.
        #
        # Desired retained result:
        #   new .1 = compressed pending
        #   new .2 = old .1
        #   new .3 = old .2
        #
        # The old final generation naturally falls outside retention.
        # Every destination is reconstructed from txn, never from a partially
        # published root generation.
        for destination_generation in range(
            policy.backup_count,
            1,
            -1,
        ):
            source_generation = destination_generation - 1
            source = txn / f"{source_generation}.gz"
            destination = self._generation(
                path,
                destination_generation,
            )

            if not source.exists():
                destination.unlink(missing_ok=True)
                continue

            publish_tmp = path.with_name(
                f"{path.name}.{destination_generation}.gz.lt05-publish"
            )
            publish_tmp.unlink(missing_ok=True)

            try:
                os.link(source, publish_tmp)
                os.replace(publish_tmp, destination)
            except Exception:
                publish_tmp.unlink(missing_ok=True)
                raise

        os.replace(
            compressed_tmp,
            self._generation(path, 1),
        )

        # Publication is complete. Atomically convert the immutable
        # transaction baseline into a commit marker. Keep it until
        # _archive_pending retires pending; this closes the crash window
        # between publication and pending.unlink().
        os.replace(txn, published)


class ToolHiveExternalLogOwner:
    """Thin LT05 adapter over the existing ToolHive containment lifecycle."""

    def __init__(
        self,
        *,
        containment,
        log_paths: tuple[Path, ...],
        real_readback: Callable[[], bool],
        lsof_runner=subprocess.run,
        sleep=time.sleep,
        stop_timeout: float = 15.0,
        start_timeout: float = 30.0,
        poll_interval: float = 0.1,
    ) -> None:
        self.containment = containment
        self.log_paths = tuple(Path(path) for path in log_paths)
        self.real_readback = real_readback
        self.lsof_runner = lsof_runner
        self.sleep = sleep
        self.stop_timeout = stop_timeout
        self.start_timeout = start_timeout
        self.poll_interval = poll_interval
        self._pre_stop_inodes: dict[Path, int | None] = {}
        self._require_new_inode: set[Path] = set()

    def is_running(self) -> bool:
        try:
            return bool(self.containment.health())
        except Exception:
            return False

    def stop(self) -> None:
        self._pre_stop_inodes = {}
        for path in self.log_paths:
            try:
                self._pre_stop_inodes[path] = path.stat().st_ino
            except FileNotFoundError:
                self._pre_stop_inodes[path] = None

        try:
            self.containment.stop()
        except Exception:
            self._pre_stop_inodes = {}
            raise

    def wait_log_closed(self, path: Path) -> bool:
        path = Path(path)
        if path not in self.log_paths:
            return False

        deadline = time.monotonic() + self.stop_timeout

        while True:
            cp = self.lsof_runner(
                ["/usr/sbin/lsof", "-nP", "--", str(path)],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if (
                cp.returncode == 1
                and not (cp.stdout or "").strip()
                and not (cp.stderr or "").strip()
            ):
                return True

            if time.monotonic() >= deadline:
                return False

            self.sleep(self.poll_interval)

    def start(self) -> None:
        self._require_new_inode = {
            path
            for path in self.log_paths
            if not path.exists()
        }
        self.containment.start()

    def _logs_reopened(self) -> bool:
        if not self._pre_stop_inodes:
            return False

        for path in self.log_paths:
            old_inode = self._pre_stop_inodes.get(path)

            try:
                current_inode = path.stat().st_ino
            except FileNotFoundError:
                return False

            if (
                path in self._require_new_inode
                and old_inode is not None
                and current_inode == old_inode
            ):
                return False

            cp = self.lsof_runner(
                ["/usr/sbin/lsof", "-nP", "--", str(path)],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if cp.returncode != 0 or not (cp.stdout or "").strip():
                return False

        return True

    def readback_ready(self) -> bool:
        deadline = time.monotonic() + self.start_timeout

        while True:
            try:
                if (
                    self.containment.health()
                    and self._logs_reopened()
                    and bool(self.real_readback())
                ):
                    self._pre_stop_inodes = {}
                    self._require_new_inode = set()
                    return True
            except Exception:
                pass

            if time.monotonic() >= deadline:
                return False

            self.sleep(self.poll_interval)




def build_production_external_log_campaign(
    *,
    data_dir: Path,
    repo_root: Path,
    home: Path | None = None,
    launchd_owner_factory: Callable[..., ExternalLogOwner] | None = None,
    toolhive_owner_factory: Callable[..., ExternalLogOwner] | None = None,
    toolhive_lifecycle_factory: Callable[[str], object] | None = None,
    toolhive_readback_factory: Callable[[str], Callable[[], bool]] | None = None,
    operator_readback: Callable[[], bool],
    chat_readback: Callable[[], bool],
    llama_readback: Callable[[], bool],
    common_max_bytes: int = 64 * 1024 * 1024,
    llama_max_bytes: int = 256 * 1024 * 1024,
    backup_count: int = 3,
) -> "ExternalLogMaintenanceCampaign":
    """Compose LT05 production owners without executing maintenance.

    Authority remains with each real owner:
    launchd services use bootout/bootstrap; ToolHive workloads use their
    existing lifecycle adapter.  This function only binds canonical paths,
    policies and readback callbacks.
    """
    home = Path.home() if home is None else Path(home)
    data_dir = Path(data_dir)
    repo_root = Path(repo_root)

    launchd_owner_factory = launchd_owner_factory or LaunchdExternalLogOwner
    toolhive_owner_factory = toolhive_owner_factory or ToolHiveExternalLogOwner

    if toolhive_lifecycle_factory is None or toolhive_readback_factory is None:
        raise ValueError("ToolHive lifecycle/readback factories are required")

    launch_agents = home / "Library" / "LaunchAgents"
    foundation_logs = home / "Library" / "Logs" / "AI-Foundation"
    toolhive_logs = home / "Library" / "Application Support" / "toolhive" / "logs"

    operator_paths = (
        foundation_logs / "operator.out.log",
        foundation_logs / "operator.err.log",
    )
    chat_paths = (
        foundation_logs / "chat-gateway.log",
        foundation_logs / "chat-gateway.err.log",
    )
    llama_paths = (
        data_dir / "local-compute" / "llama-swap.log",
    )

    operator = launchd_owner_factory(
        label="dev.quest7070.ai-foundation.operator",
        plist=launch_agents / "dev.quest7070.ai-foundation.operator.plist",
        log_paths=operator_paths,
        readback=operator_readback,
    )
    chat = launchd_owner_factory(
        label="dev.quest7070.ai-foundation.chat-gateway",
        plist=launch_agents / "dev.quest7070.ai-foundation.chat-gateway.plist",
        log_paths=chat_paths,
        readback=chat_readback,
    )
    llama = launchd_owner_factory(
        label="dev.quest7070.ai-foundation.llama-swap",
        plist=launch_agents / "dev.quest7070.ai-foundation.llama-swap.plist",
        log_paths=llama_paths,
        readback=llama_readback,
    )

    groups = [
        ExternalLogOwnerGroup(
            "operator",
            tuple(
                ExternalLogPolicy(path, common_max_bytes, backup_count)
                for path in operator_paths
            ),
            operator,
        ),
        ExternalLogOwnerGroup(
            "chat-gateway",
            tuple(
                ExternalLogPolicy(path, common_max_bytes, backup_count)
                for path in chat_paths
            ),
            chat,
        ),
        ExternalLogOwnerGroup(
            "llama-swap",
            tuple(
                ExternalLogPolicy(path, llama_max_bytes, backup_count)
                for path in llama_paths
            ),
            llama,
        ),
    ]

    for name in ("ai-foundation-fs", "ai-foundation-repo"):
        log_path = toolhive_logs / f"{name}.log"
        lifecycle = toolhive_lifecycle_factory(name)
        owner = toolhive_owner_factory(
            containment=lifecycle,
            log_paths=(log_path,),
            real_readback=toolhive_readback_factory(name),
        )
        groups.append(
            ExternalLogOwnerGroup(
                name,
                (ExternalLogPolicy(log_path, common_max_bytes, backup_count),),
                owner,
            )
        )

    return ExternalLogMaintenanceCampaign(
        maintenance=ExternalLogMaintenance(),
        lease_path=data_dir / "external-log-maintenance.lock",
        groups=tuple(groups),
    )

@dataclass(frozen=True)
class ExternalLogOwnerGroup:
    name: str
    policies: tuple[ExternalLogPolicy, ...]
    owner: ExternalLogOwner


@dataclass(frozen=True)
class CampaignResult:
    status: MaintenanceStatus
    groups: tuple[tuple[str, GroupMaintenanceResult], ...]
    detail: str


class ExternalLogMaintenanceStateStore:
    """Atomic single-record LT05 evidence; independent of long-term health."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, result: CampaignResult, *, checked_at: float) -> None:
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "checked_at": checked_at,
            "status": result.status.value,
            "detail": result.detail,
            "groups": [
                {
                    "name": name,
                    "status": group.status.value,
                    "detail": group.detail,
                }
                for name, group in result.groups
            ],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"), sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def load(self):
        import json

        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        return value


def external_log_maintenance_notice(store):
    """Project failed LT05 state into the existing HumanNotice boundary."""
    from .human_operations import HumanNotice

    row = store.load()
    if not isinstance(row, dict):
        return ()

    status = row.get("status")
    if status not in {"FAILED_RECOVERED", "FAILED_UNRECOVERED"}:
        return ()

    groups = row.get("groups")
    failed = []

    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_status = group.get("status")
            if group_status not in {
                "FAILED_RECOVERED",
                "FAILED_UNRECOVERED",
            }:
                continue
            name = str(group.get("name") or "unknown")
            detail = str(group.get("detail") or group_status)
            failed.append(f"{name}: {detail}")

    detail = "; ".join(failed[:4])
    if not detail:
        detail = str(row.get("detail") or status)

    if status == "FAILED_UNRECOVERED":
        summary = "External log maintenance failed and owner recovery is incomplete."
    else:
        summary = "External log maintenance failed but owner recovery completed."

    try:
        updated_at = float(row.get("checked_at") or 0)
    except (TypeError, ValueError):
        updated_at = 0.0

    return (
        HumanNotice(
            3,
            "system",
            "external-log-maintenance",
            "FAILED",
            summary,
            detail,
            False,
            False,
            updated_at,
        ),
    )


class ExternalLogMaintenanceCampaign:
    """One bounded external-log mutation campaign.

    Scheduling and human notification remain outside this object.
    One cross-process lease covers the complete campaign so independently
    scheduled/manual invocations cannot overlap owner stop/restart windows.
    """

    def __init__(
        self,
        *,
        maintenance: ExternalLogMaintenance,
        lease_path: Path,
        groups: tuple[ExternalLogOwnerGroup, ...],
    ) -> None:
        if not groups:
            raise ValueError("external-log campaign groups required")

        names = [group.name for group in groups]
        if len(names) != len(set(names)):
            raise ValueError("external-log campaign group names must be unique")

        self.maintenance = maintenance
        self.lease_path = Path(lease_path)
        self.groups = groups

    def run_once(self) -> CampaignResult:
        completed: list[tuple[str, GroupMaintenanceResult]] = []

        with ExternalLogMaintenanceLease(self.lease_path).acquire() as acquired:
            if not acquired:
                return CampaignResult(
                    MaintenanceStatus.NOOP,
                    (),
                    "maintenance-already-running",
                )

            for group in self.groups:
                result = self.maintenance.run_group(
                    group.policies,
                    group.owner,
                )
                completed.append((group.name, result))

                # Availability dominates cleanup. Once an owner cannot be
                # restored, do not take another independent owner offline.
                if result.status is MaintenanceStatus.FAILED_UNRECOVERED:
                    return CampaignResult(
                        MaintenanceStatus.FAILED_UNRECOVERED,
                        tuple(completed),
                        f"owner-unrecovered:{group.name}",
                    )

        statuses = tuple(result.status for _, result in completed)

        if any(
            status is MaintenanceStatus.FAILED_RECOVERED
            for status in statuses
        ):
            status = MaintenanceStatus.FAILED_RECOVERED
        elif any(
            status is MaintenanceStatus.SUCCESS
            for status in statuses
        ):
            status = MaintenanceStatus.SUCCESS
        else:
            status = MaintenanceStatus.NOOP

        return CampaignResult(
            status,
            tuple(completed),
            "campaign-complete",
        )

class LaunchdExternalLogOwner:
    """Owner-safe lifecycle adapter for one canonical launchd LaunchAgent.

    This adapter owns no rotation policy.  It only provides the lifecycle
    boundary required by ExternalLogMaintenance:

      loaded/running -> bootout -> prove every target log descriptor closed
      -> bootstrap -> service-specific readback

    The caller supplies the readback function because service health semantics
    belong to the service, not launchd.
    """

    def __init__(
        self,
        *,
        label: str,
        plist: Path,
        log_paths: tuple[Path, ...],
        readback: Callable[[], bool],
        uid: int | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        lsof_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        stop_timeout: float = 15.0,
        start_timeout: float = 30.0,
        poll_interval: float = 0.1,
    ) -> None:
        if not label:
            raise ValueError("launchd label required")
        if not log_paths:
            raise ValueError("launchd log paths required")

        self.label = label
        self.plist = Path(plist)
        self.log_paths = tuple(Path(p) for p in log_paths)
        self.readback = readback
        self.uid = os.getuid() if uid is None else uid
        self.runner = runner
        self.lsof_runner = lsof_runner
        self.sleep = sleep
        self.stop_timeout = stop_timeout
        self.start_timeout = start_timeout
        self.poll_interval = poll_interval
        self._pre_stop_inodes: dict[Path, int | None] = {}
        self._require_new_inode: set[Path] = set()

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    @property
    def service(self) -> str:
        return f"{self.domain}/{self.label}"

    def _launchctl(
        self,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        return self.runner(
            ["/bin/launchctl", *args],
            capture_output=True,
            text=True,
            timeout=15,
        )

    def is_running(self) -> bool:
        # For launchd the maintenance pre-state is whether this job is loaded,
        # not whether launchd happens to report the process as running at this
        # instant. A loaded KeepAlive job must be restored after bootout even
        # if it is temporarily between process instances. An unloaded job must
        # remain unloaded.
        cp = self._launchctl("print", self.service)
        return cp.returncode == 0

    def stop(self) -> None:
        # Capture active inodes before bootout. After bootstrap the active
        # paths must be reopened onto different inodes before real service
        # readback can succeed.
        self._pre_stop_inodes = {}
        for path in self.log_paths:
            try:
                self._pre_stop_inodes[path] = path.stat().st_ino
            except FileNotFoundError:
                self._pre_stop_inodes[path] = None

        cp = self._launchctl(
            "bootout",
            self.domain,
            str(self.plist),
        )
        if cp.returncode != 0:
            self._pre_stop_inodes = {}
            raise RuntimeError(
                "launchd bootout failed:"
                f"{cp.returncode}:"
                f"{(cp.stderr or cp.stdout or '').strip()}"
            )

    def wait_log_closed(self, path: Path) -> bool:
        target = str(Path(path))
        deadline = time.monotonic() + self.stop_timeout

        while True:
            cp = self.lsof_runner(
                ["/usr/sbin/lsof", "-nP", "--", target],
                capture_output=True,
                text=True,
                timeout=5,
            )

            # lsof uses return code 1 both for "no matching descriptor"
            # and for some path/query errors. Only a completely silent
            # no-match is acceptable as descriptor-close proof.
            if (
                cp.returncode == 1
                and not (cp.stdout or "").strip()
                and not (cp.stderr or "").strip()
            ):
                return True

            if time.monotonic() >= deadline:
                return False

            self.sleep(self.poll_interval)

    def start(self) -> None:
        # Rotation authority is observable here without extending the
        # owner-neutral protocol: after maintenance moves an active path to
        # pending, that active path is absent immediately before owner start.
        # Paths that remain present were not moved and may legitimately retain
        # their inode across the bounded recovery restart.
        self._require_new_inode = {
            path
            for path in self.log_paths
            if not path.exists()
        }

        cp = self._launchctl(
            "bootstrap",
            self.domain,
            str(self.plist),
        )
        if cp.returncode != 0:
            raise RuntimeError(
                "launchd bootstrap failed:"
                f"{cp.returncode}:"
                f"{(cp.stderr or cp.stdout or '').strip()}"
            )

    def _logs_reopened(self) -> bool:
        if not self._pre_stop_inodes:
            return False

        for path in self.log_paths:
            old_inode = self._pre_stop_inodes.get(path)
            try:
                current_inode = path.stat().st_ino
            except FileNotFoundError:
                return False

            if (
                path in self._require_new_inode
                and old_inode is not None
                and current_inode == old_inode
            ):
                return False

            cp = self.lsof_runner(
                ["/usr/sbin/lsof", "-nP", "--", str(path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if cp.returncode != 0 or not (cp.stdout or "").strip():
                return False

        return True

    def readback_ready(self) -> bool:
        deadline = time.monotonic() + self.start_timeout

        while True:
            try:
                if (
                    self.is_running()
                    and self._logs_reopened()
                    and bool(self.readback())
                ):
                    self._pre_stop_inodes = {}
                    self._require_new_inode = set()
                    return True
            except Exception:
                pass

            if time.monotonic() >= deadline:
                return False

            self.sleep(self.poll_interval)
