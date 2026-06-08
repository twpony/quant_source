"""CSV file I/O utilities — consistent reading/writing with project defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from utils.logger import log


class CsvIO:
    """Read and write CSV files with project-standard defaults.

    Provides a thin, consistent wrapper around ``pandas.read_csv()`` and
    ``DataFrame.to_csv()`` so that encoding, index handling, and error
    logging are uniform across the codebase.

    Usage::

        from utils.csv_io import CsvIO

        io = CsvIO()
        df = io.read("/path/to/file.csv")
        io.write(df, "/path/to/output.csv")
    """

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    DEFAULT_ENCODING: str = "utf-8-sig"
    DEFAULT_READ_KWARGS: dict[str, Any] = {
        "encoding": DEFAULT_ENCODING,
        "low_memory": False,
        "dtype": str,
    }
    DEFAULT_WRITE_KWARGS: dict[str, Any] = {
        "encoding": DEFAULT_ENCODING,
        "index": False,
    }

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(
        self,
        filepath: str | Path,
        **kwargs: Any,
    ) -> pd.DataFrame | None:
        """Read a CSV file into a DataFrame.

        Args:
            filepath: Path to the CSV file.
            **kwargs: Additional arguments forwarded to ``pandas.read_csv()``.
                      Override default encoding/index behaviour as needed.

        Returns:
            DataFrame if successful, ``None`` on error.
        """
        path = Path(filepath)
        log.info("Reading CSV: %s", path)

        if not path.exists():
            log.error("CSV file not found: %s", path)
            return None

        try:
            params: dict[str, Any] = {**self.DEFAULT_READ_KWARGS, **kwargs}
            df = pd.read_csv(path, **params)
            log.info("Read %d rows × %d columns from %s", len(df), len(df.columns), path)
            return df
        except Exception:
            log.exception("Failed to read CSV: %s", path)
            return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(
        self,
        df: pd.DataFrame,
        filepath: str | Path,
        mkdir: bool = True,
        **kwargs: Any,
    ) -> bool:
        """Write a DataFrame to a CSV file.

        Args:
            df: DataFrame to write.
            filepath: Destination path.
            mkdir: If ``True``, create parent directories when they do not exist.
            **kwargs: Additional arguments forwarded to ``DataFrame.to_csv()``.
                      Override default encoding/index behaviour as needed.

        Returns:
            ``True`` on success, ``False`` on error.
        """
        path = Path(filepath)

        if mkdir:
            path.parent.mkdir(parents=True, exist_ok=True)

        log.info("Writing CSV: %s (%d rows)", path, len(df))

        try:
            params: dict[str, Any] = {**self.DEFAULT_WRITE_KWARGS, **kwargs}
            df.to_csv(path, **params)
            size = path.stat().st_size
            log.info("Wrote %s (%d bytes)", path, size)
            return True
        except Exception:
            log.exception("Failed to write CSV: %s", path)
            return False

    # ------------------------------------------------------------------
    # Convenience: read with automatic encoding detection
    # ------------------------------------------------------------------

    @staticmethod
    def _try_read(filepath: str | Path, encoding: str, **kwargs: Any) -> pd.DataFrame | None:
        """Attempt to read a CSV with a specific encoding; return ``None`` on failure."""
        try:
            return pd.read_csv(filepath, encoding=encoding, low_memory=False, **kwargs)
        except (UnicodeDecodeError, LookupError):
            return None

    def read_auto_encoding(
        self,
        filepath: str | Path,
        encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "gbk", "gb2312", "latin-1"),
        **kwargs: Any,
    ) -> pd.DataFrame | None:
        """Read a CSV file, trying multiple encodings in order.

        Useful when the file may originate from external sources (e.g. Windows
        Excel exports that use GBK).

        Args:
            filepath: Path to the CSV file.
            encodings: Encodings to try, in priority order.
            **kwargs: Additional arguments forwarded to ``pandas.read_csv()``.

        Returns:
            DataFrame if any encoding succeeds, ``None`` otherwise.
        """
        path = Path(filepath)

        if not path.exists():
            log.error("CSV file not found: %s", path)
            return None

        for enc in encodings:
            df = self._try_read(path, enc, **kwargs)
            if df is not None:
                log.info(
                    "Read %d rows × %d columns from %s (encoding=%s)",
                    len(df),
                    len(df.columns),
                    path,
                    enc,
                )
                return df
            log.debug("Encoding %s failed for %s", enc, path)

        log.error("All encodings failed for %s (tried: %s)", path, encodings)
        return None


# ------------------------------------------------------------------
# Module-level convenience instance
# ------------------------------------------------------------------

csv = CsvIO()
