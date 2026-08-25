import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAIRS_FILE = PROJECT_ROOT / "data" / "pairs.json"


@dataclass
class MonitoringPair:
    """A DEX pair monitored for price deviation."""

    chain: str
    pair_address: str
    name: str
    expected_price: float = 1.0
    pair_type: str = "stable/stable"


@dataclass
class Config:
    """Application settings loaded from environment variables."""

    bot_token: str = os.getenv("BOT_TOKEN", "")

    redis_host: str = os.getenv("REDIS_HOST", "redis")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    redis_channel: str = os.getenv("REDIS_CHANNEL", "depeg_alerts")

    check_interval: int = int(os.getenv("CHECK_INTERVAL", 30))
    depeg_threshold: float = float(os.getenv("DEPEG_THRESHOLD", 2.0))

    dexscreener_api_url: str = os.getenv(
        "DEXSCREENER_API_URL",
        "https://api.dexscreener.com/latest/dex",
    )
    monitoring_pairs_file: Path = Path(
        os.getenv("MONITORING_PAIRS_FILE", str(DEFAULT_PAIRS_FILE))
    )
    monitoring_pairs: Optional[List[MonitoringPair]] = None

    def __post_init__(self) -> None:
        if self.monitoring_pairs is None:
            self.monitoring_pairs = self._load_pairs_from_json()

    def _load_pairs_from_json(self) -> List[MonitoringPair]:
        """Load monitored pairs from the configured JSON file."""

        try:
            with self.monitoring_pairs_file.open("r", encoding="utf-8") as file:
                pairs_data = json.load(file)

            pairs = [
                MonitoringPair(
                    chain=pair["chain"],
                    pair_address=pair["pair_address"],
                    name=pair["name"],
                    expected_price=pair.get("expected_price", 1.0),
                    pair_type=pair.get("pair_type", "stable/stable"),
                )
                for pair in pairs_data
            ]

            print(f"Loaded {len(pairs)} pairs from {self.monitoring_pairs_file}")
            return pairs

        except FileNotFoundError:
            print(f"Pairs file not found: {self.monitoring_pairs_file}")
            print("Run: python scripts/update_pairs.py")
            return []

        except Exception as error:
            print(f"Failed to load monitoring pairs: {error}")
            return []


config = Config()

