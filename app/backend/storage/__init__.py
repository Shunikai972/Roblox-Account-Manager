"""Storage lifecycle helpers: backups and legacy-data migration."""

from .backups import BackupError, VersionedBackupManager
from .legacy_migrator import (
    LegacyDataMigrator,
    LegacyDetection,
    LegacyFormat,
    LegacyMigrationError,
    MigrationReport,
)
from .metadata_transfer import (
    MetadataImportReport,
    MetadataTransfer,
    MetadataTransferError,
)

__all__ = [
    "BackupError",
    "VersionedBackupManager",
    "LegacyDataMigrator",
    "LegacyDetection",
    "LegacyFormat",
    "LegacyMigrationError",
    "MigrationReport",
    "MetadataImportReport",
    "MetadataTransfer",
    "MetadataTransferError",
]
