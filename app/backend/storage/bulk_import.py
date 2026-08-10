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

        # Replace commas between entries if commas are used as account separators (e.g. u1:p1, u2:p2)
        # But handle comma-separated fields (u1,p1)
        raw_lines = raw_text.replace("\r", "\n").split("\n")
        items = []
        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            # If line has multiple accounts separated by comma (e.g., user1:pass1, user2:pass2)
            if "," in line and ":" in line and not line.startswith("_|WARNING"):
                sub_parts = [p.strip() for p in line.split(",") if p.strip()]
                items.extend(sub_parts)
            else:
                items.append(line)

        for line in items:
            # Check for raw cookie
            if "_|WARNING" in line:
                if "::" in line:
                    parts = line.split("::", 1)
                    results.append({"username": parts[0].strip(), "cookie": parts[1].strip(), "password": None})
                    continue
                if ":" in line and USERNAME_PATTERN.match(line.split(":")[0].strip()):
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

            # Single username
            if USERNAME_PATTERN.match(line):
                results.append({"username": line, "password": None, "cookie": None})

        return results
