"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


@dataclass
class Settings:
    """Central configuration for the quant data system."""

    # Tushare
    tushare_token: str = field(
        default_factory=lambda: os.getenv("TUSHARE_TOKEN", "")
    )

    # Storage paths
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("DATA_DIR", str(Path.cwd() / "data_files"))
        )
    )
    duckdb_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("DUCKDB_PATH", "")
        )
    )
    log_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("LOG_DIR", str(Path.cwd() / "logs"))
        )
    )

    # Data parameters
    history_years: int = 15
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds

    def __post_init__(self):
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if not self.duckdb_path or str(self.duckdb_path) == ".":
            self.duckdb_path = self.data_dir / "quant.duckdb"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def daily_parquet_dir(self) -> Path:
        return self.data_dir / "daily"

    @property
    def stock_basic_parquet_path(self) -> Path:
        return self.data_dir / "stock_basic.parquet"

    @property
    def income_parquet_dir(self) -> Path:
        return self.data_dir / "income"

    @property
    def balancesheet_parquet_dir(self) -> Path:
        return self.data_dir / "balancesheet"

    @property
    def trade_calendar_parquet_dir(self) -> Path:
        return self.data_dir / "trade_calendar"

    @property
    def st_stocks_parquet_path(self) -> Path:
        return self.data_dir / "st_stocks.parquet"


# Global singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the global Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
