"""Atomic, checksummed, versioned backups for local application data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any, Mapping
from uuid import uuid4

from app.backend.security.redaction import redact_mapping


BACKUP_FORMAT_VERSION = 1


class BackupError(RuntimeError):
    """Raised when a backup cannot be safely written, verified, or restored."""


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """An immutable reference to a verified backup manifest and payload."""

    backup_id: str
    created_at: str
    app_version: str
    format_version: int
    source_name: str
    data_file: str
    manifest_file: str
    sha256: str
    size_bytes: int
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def timestamp(self) -> datetime:
        return datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))


class VersionedBackupManager:
    """Create atomic backups under an application-controlled directory.

    A backup becomes visible only once both a data file and its manifest exist.
    Manifest verification includes a SHA-256 checksum, and restore refuses to
    overwrite a destination unless the caller explicitly opts in.
    """

    def __init__(self, backup_dir: str | Path, *, app_version: str = "0") -> None:
        self.backup_dir = Path(backup_dir).expanduser().resolve()
        self.app_version = str(app_version)
        self._lock = threading.RLock()

    def create_backup(
        self,
        source: str | Path,
        *,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> BackupRecord:
        """Copy a regular file into a verified backup without altering source."""

        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise BackupError(f"Backup source is not a regular file: {source_path}")

        with self._lock:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            record = self._new_record(source_path, label=label, metadata=metadata)
            payload_path = self.backup_dir / record.data_file
            self._copy_file_atomically(source_path, payload_path)
            finalized = self._finalize_record(record, payload_path)
            self._write_manifest_atomically(finalized)
            return finalized

    def create_sqlite_backup(
        self,
        database: str | Path,
        *,
        label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> BackupRecord:
        """Make a consistent SQLite snapshot using SQLite's backup API.

        Unlike a raw file copy, this works correctly while the source database
        is open and using WAL mode.
        """

        database_path = Path(database).expanduser().resolve()
        if not database_path.is_file():
            raise BackupError(f"SQLite database does not exist: {database_path}")

        with self._lock:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            record = self._new_record(database_path, label=label, metadata=metadata)
            payload_path = self.backup_dir / record.data_file
            temp_path = self._temporary_path(payload_path)
            source_connection: sqlite3.Connection | None = None
            destination_connection: sqlite3.Connection | None = None
            try:
                # sqlite3 connection context managers commit/rollback but do
                # not close.  Explicit closes are required on Windows before
                # atomically replacing the temporary snapshot.
                source_connection = sqlite3.connect(database_path)
                destination_connection = sqlite3.connect(temp_path)
                source_connection.backup(destination_connection)
                destination_connection.commit()
                destination_connection.close()
                destination_connection = None
                source_connection.close()
                source_connection = None
                self._fsync_file(temp_path)
                os.replace(temp_path, payload_path)
                self._fsync_directory(self.backup_dir)
            except (OSError, sqlite3.Error) as exc:
                if destination_connection is not None:
                    destination_connection.close()
                if source_connection is not None:
                    source_connection.close()
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise BackupError(f"Could not create SQLite backup: {exc}") from exc

            finalized = self._finalize_record(record, payload_path)
            self._write_manifest_atomically(finalized)
            return finalized

    def list_backups(self, *, verify: bool = False) -> list[BackupRecord]:
        """Return recognized backups newest first, ignoring incomplete artifacts."""

        if not self.backup_dir.exists():
            return []
        records: list[BackupRecord] = []
        for manifest_path in self.backup_dir.glob("*.manifest.json"):
            try:
                record = self._read_manifest(manifest_path)
                payload_path = self._payload_path(record)
                if not payload_path.is_file():
                    continue
                if verify and not self.verify(record):
                    continue
                records.append(record)
            except (BackupError, OSError, ValueError, TypeError, json.JSONDecodeError):
                # Partial or hand-edited manifests are never candidates for
                # automated restore; diagnostics can enumerate them separately.
                continue
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def verify(self, record: BackupRecord | str) -> bool:
        """Check that the payload still matches the manifest checksum and size."""

        current = self._resolve_record(record)
        payload_path = self._payload_path(current)
        if not payload_path.is_file() or payload_path.stat().st_size != current.size_bytes:
            return False
        return _sha256_file(payload_path) == current.sha256

    def restore(
        self,
        record: BackupRecord | str,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Restore a verified payload via a same-directory atomic replacement.

        This method intentionally does not replace an existing destination until
        ``overwrite=True`` is supplied by a higher-level, confirmed workflow.
        """

        current = self._resolve_record(record)
        if not self.verify(current):
            raise BackupError("Refusing to restore an invalid or modified backup.")

        destination_path = Path(destination).expanduser().resolve()
        if destination_path.exists() and not overwrite:
            raise BackupError("Destination exists; explicit overwrite is required.")
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        source_path = self._payload_path(current)
        temporary = self._temporary_path(destination_path)
        try:
            self._copy_file(source_path, temporary)
            self._fsync_file(temporary)
            if destination_path.exists() and not overwrite:
                # Recheck after the copy to avoid a time-of-check/time-of-use
                # surprise if another process created it.
                raise BackupError("Destination was created during restore.")
            os.replace(temporary, destination_path)
            self._fsync_directory(destination_path.parent)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise BackupError(f"Could not restore backup: {exc}") from exc
        except BackupError:
            temporary.unlink(missing_ok=True)
            raise
        return destination_path

    def get_backup(self, backup_id: str) -> BackupRecord:
        """Load a known backup by opaque identifier."""

        if not backup_id or any(character in backup_id for character in "\\/"):
            raise BackupError("Invalid backup identifier.")
        manifest_path = self.backup_dir / f"{backup_id}.manifest.json"
        if not manifest_path.is_file():
            raise BackupError("Backup was not found.")
        return self._read_manifest(manifest_path)

    def _resolve_record(self, record: BackupRecord | str) -> BackupRecord:
        return self.get_backup(record) if isinstance(record, str) else record

    def _new_record(
        self,
        source: Path,
        *,
        label: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> BackupRecord:
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_id = f"v{BACKUP_FORMAT_VERSION}-{timestamp}-{uuid4().hex[:12]}"
        source_suffix = source.suffix if source.suffix else ".bin"
        return BackupRecord(
            backup_id=backup_id,
            created_at=created_at,
            app_version=self.app_version,
            format_version=BACKUP_FORMAT_VERSION,
            source_name=source.name,
            data_file=f"{backup_id}{source_suffix}",
            manifest_file=f"{backup_id}.manifest.json",
            sha256="",
            size_bytes=0,
            label=_normalize_label(label),
            metadata=dict(redact_mapping(dict(metadata or {}))),
        )

    def _finalize_record(self, record: BackupRecord, payload_path: Path) -> BackupRecord:
        return BackupRecord(
            **{
                **asdict(record),
                "sha256": _sha256_file(payload_path),
                "size_bytes": payload_path.stat().st_size,
            }
        )

    def _write_manifest_atomically(self, record: BackupRecord) -> None:
        manifest_path = self.backup_dir / record.manifest_file
        encoded = json.dumps(
            asdict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self._write_bytes_atomically(manifest_path, encoded)

    def _read_manifest(self, manifest_path: Path) -> BackupRecord:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_name = manifest_path.name
        record = BackupRecord(**raw)
        if record.format_version != BACKUP_FORMAT_VERSION:
            raise BackupError("Unsupported backup manifest version.")
        if record.manifest_file != expected_name:
            raise BackupError("Backup manifest filename does not match its payload.")
        if Path(record.data_file).name != record.data_file:
            raise BackupError("Backup manifest has an unsafe data filename.")
        if not _is_sha256(record.sha256) or record.size_bytes < 0:
            raise BackupError("Backup manifest checksum is invalid.")
        return record

    def _payload_path(self, record: BackupRecord) -> Path:
        path = (self.backup_dir / record.data_file).resolve()
        try:
            path.relative_to(self.backup_dir)
        except ValueError as exc:
            raise BackupError("Backup payload escapes the configured backup directory.") from exc
        return path

    def _copy_file_atomically(self, source: Path, destination: Path) -> None:
        temporary = self._temporary_path(destination)
        try:
            self._copy_file(source, temporary)
            self._fsync_file(temporary)
            os.replace(temporary, destination)
            self._fsync_directory(destination.parent)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise BackupError(f"Could not create backup: {exc}") from exc

    @staticmethod
    def _copy_file(source: Path, destination: Path) -> None:
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        return destination.with_name(f".{destination.name}.{uuid4().hex}.partial")

    @staticmethod
    def _write_bytes_atomically(destination: Path, data: bytes) -> None:
        temporary = VersionedBackupManager._temporary_path(destination)
        try:
            with temporary.open("xb") as output_file:
                output_file.write(data)
                output_file.flush()
                os.fsync(output_file.fileno())
            os.replace(temporary, destination)
            VersionedBackupManager._fsync_directory(destination.parent)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise BackupError(f"Could not write backup manifest: {exc}") from exc

    @staticmethod
    def _fsync_file(path: Path) -> None:
        # Windows requires a writable handle for FlushFileBuffers (which backs
        # ``os.fsync``); every caller passes a newly created temporary file.
        with path.open("rb+") as stream:
            os.fsync(stream.fileno())

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        # Windows cannot open a directory with the same semantics; successful
        # atomic replacement is still the strongest portable guarantee there.
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(str(value).split())
    return compact[:120] if compact else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


__all__ = ["BACKUP_FORMAT_VERSION", "BackupError", "BackupRecord", "VersionedBackupManager"]
