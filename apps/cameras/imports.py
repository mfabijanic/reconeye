"""Source-agnostic import layer for go2rtc instances.

The design intentionally separates *where* instance definitions come from
(CSV today, an external API/inventory system tomorrow) from *how* they are
validated and persisted. Add a new import source by subclassing
``BaseInstanceImportSource`` and yielding ``InstanceImportRow`` objects; the
service-layer import/preview functions stay unchanged.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Iterator

# Canonical CSV columns. The header is required (case-insensitive,
# order-independent). ``name`` and ``host`` are mandatory; the rest have
# sensible defaults.
REQUIRED_COLUMNS = ("name", "host")
OPTIONAL_DEFAULTS = {
    "scheme": "http",
    "port": "1984",
    "path": "",
    "group_label": "",
}
VALID_SCHEMES = ("http", "https")


@dataclass
class InstanceImportRow:
    """Normalized, source-agnostic representation of one go2rtc instance."""

    name: str
    host: str
    scheme: str = "http"
    port: int = 1984
    path: str = ""
    group_label: str = ""
    # Row-level validation errors (empty list == valid row).
    errors: list[str] = field(default_factory=list)
    # 1-based source line number (for CSV: the file line) for reporting.
    source_line: int | None = None

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def base_url_preview(self) -> str:
        base = f"{self.scheme}://{self.host}:{self.port}"
        path = (self.path or "").strip("/")
        return f"{base}/{path}" if path else base


class BaseInstanceImportSource:
    """Abstract import source.

    Subclasses implement :meth:`iter_rows` to yield ``InstanceImportRow``
    objects. Rows may be invalid (carry ``errors``); validation is the
    source's responsibility so per-source quirks stay encapsulated.
    """

    def iter_rows(self) -> Iterator[InstanceImportRow]:  # pragma: no cover - abstract
        raise NotImplementedError


class CsvInstanceImportSource(BaseInstanceImportSource):
    """Parse go2rtc instances from CSV text or bytes.

    Expected header (case-insensitive, order-independent)::

        name, host[, scheme, port, path, group_label]
    """

    def __init__(self, content: str | bytes):
        if isinstance(content, bytes):
            # utf-8-sig tolerates a leading BOM written by spreadsheet apps.
            content = content.decode("utf-8-sig", errors="replace")
        self._content = content

    def iter_rows(self) -> Iterator[InstanceImportRow]:
        buffer = io.StringIO(self._content)
        reader = csv.DictReader(buffer)

        if reader.fieldnames is None:
            yield InstanceImportRow(
                name="",
                host="",
                source_line=1,
                errors=["CSV is empty or has no header row."],
            )
            return

        # Map canonical lower-cased column name -> actual header key.
        normalized = {(h or "").strip().lower(): h for h in reader.fieldnames}
        missing = [c for c in REQUIRED_COLUMNS if c not in normalized]
        if missing:
            yield InstanceImportRow(
                name="",
                host="",
                source_line=1,
                errors=[f"Missing required column(s): {', '.join(missing)}."],
            )
            return

        def cell(raw: dict, key: str) -> str:
            src_key = normalized.get(key)
            return (raw.get(src_key) or "").strip() if src_key else ""

        # Enumerate from 2: line 1 is the header.
        for idx, raw in enumerate(reader, start=2):
            name = cell(raw, "name")
            host = cell(raw, "host")
            scheme_raw = cell(raw, "scheme")
            port_raw = cell(raw, "port")
            path = cell(raw, "path").strip("/")
            group_label = cell(raw, "group_label")

            # Skip completely blank lines silently (trailing newlines etc.).
            if not any([name, host, scheme_raw, port_raw, path, group_label]):
                continue

            scheme = (scheme_raw or OPTIONAL_DEFAULTS["scheme"]).lower()
            errors: list[str] = []

            if not name:
                errors.append("Missing name.")
            if not host:
                errors.append("Missing host.")
            if scheme not in VALID_SCHEMES:
                errors.append(f"Invalid scheme '{scheme}' (use http/https).")

            port = 1984
            try:
                port = int(port_raw or OPTIONAL_DEFAULTS["port"])
                if not (1 <= port <= 65535):
                    raise ValueError
            except (TypeError, ValueError):
                port = 1984
                errors.append(f"Invalid port '{port_raw}'.")

            yield InstanceImportRow(
                name=name,
                host=host,
                scheme=scheme,
                port=port,
                path=path,
                group_label=group_label,
                errors=errors,
                source_line=idx,
            )
