"""Bulk account import parser for legacy user:pass, user:pass:cookie, and raw cookie formats."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("astro.bulk_import")

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


class BulkAccountImporter:
    """Parses raw text containing account credentials in legacy formats."""

    @staticmethod
    def parse_text(raw_text: str) -> list[dict[str, Any]]:
        """Parse raw text lines or comma-separated lists into structured account dictionaries."""
        results = []
        if not raw_text or not isinstance(raw_text, str):
            return results

        # A comma can separate either two ``user:pass`` records or the fields
        # of one ``user,password,cookie`` record. Split only when every segment
        # looks like a colon-form record; otherwise keep the line intact.
        raw_lines = raw_text.replace("\r", "\n").split("\n")
        items = []
        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            comma_parts = [part.strip() for part in line.split(",") if part.strip()]
            if (
                "_|WARNING" not in line
                and len(comma_parts) > 1
                and all(":" in part for part in comma_parts)
            ):
                items.extend(comma_parts)
            else:
                items.append(line)

        for line in items:
            # Check for raw cookie
            if "_|WARNING" in line:
                if "::" in line:
                    parts = line.split("::", 1)
                    results.append({"username": parts[0].strip(), "cookie": parts[1].strip(), "password": None})
                    continue
                if "," in line:
                    parts = [part.strip() for part in line.split(",", 2)]
                    if len(parts) == 3 and USERNAME_PATTERN.match(parts[0]) and "_|WARNING" in parts[2]:
                        results.append({"username": parts[0], "password": parts[1], "cookie": parts[2]})
                        continue
                    if len(parts) == 2 and USERNAME_PATTERN.match(parts[0]) and "_|WARNING" in parts[1]:
                        results.append({"username": parts[0], "password": None, "cookie": parts[1]})
                        continue
                if ":" in line and USERNAME_PATTERN.match(line.split(":")[0].strip()):
                    username, remainder = line.split(":", 1)
                    if remainder.strip().startswith("_|WARNING"):
                        results.append({"username": username.strip(), "password": None, "cookie": remainder.strip()})
                        continue
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        results.append({"username": parts[0].strip(), "password": parts[1].strip(), "cookie": parts[2].strip()})
                        continue
                    if len(parts) == 2:
                        results.append({"username": parts[0].strip(), "password": None, "cookie": parts[1].strip()})
                        continue
                results.append({"username": "", "cookie": line, "password": None})
                continue

            # Check for comma format: username,password or username,password,cookie
            if "," in line:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and USERNAME_PATTERN.match(parts[0]):
                    results.append({
                        "username": parts[0],
                        "password": parts[1],
                        "cookie": parts[2] if len(parts) >= 3 and "_|WARNING" in parts[2] else None,
                    })
                    continue

            # Check for colon format: user:pass
            if ":" in line:
                parts = [p.strip() for p in line.split(":", 2)]
                if len(parts) == 2 and USERNAME_PATTERN.match(parts[0]):
                    results.append({"username": parts[0], "password": parts[1], "cookie": None})
                    continue
                # RAM tolerated a trailing third field such as an email.
                # Preserve the identity/password and deliberately discard the
                # unsupported extra field instead of losing the whole record.
                if len(parts) == 3 and USERNAME_PATTERN.match(parts[0]):
                    results.append({"username": parts[0], "password": parts[1], "cookie": None})
                    continue

            # Single username
            if USERNAME_PATTERN.match(line):
                results.append({"username": line, "password": None, "cookie": None})

        return BulkAccountImporter._deduplicate(results)

    @staticmethod
    def _deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse repeated pasted records without logging their contents."""

        ordered: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        for record in records:
            username = (record.get("username") or "").strip()
            cookie = record.get("cookie") or ""
            key = username.casefold() if username else "cookie:" + cookie
            if not key:
                continue
            if key not in seen:
                seen[key] = len(ordered)
                ordered.append(record)
                continue
            existing_index = seen[key]
            if BulkAccountImporter._richness(record) > BulkAccountImporter._richness(
                ordered[existing_index]
            ):
                ordered[existing_index] = record
        if len(ordered) != len(records):
            logger.info(
                "Bulk import collapsed %s duplicate record(s)",
                len(records) - len(ordered),
            )
        return ordered

    @staticmethod
    def _richness(record: dict[str, Any]) -> int:
        # A validated session is immediately usable and therefore wins over a
        # password-only record when both refer to the same username.
        return (2 if record.get("cookie") else 0) + (1 if record.get("password") else 0)
