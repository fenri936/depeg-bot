import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()

@dataclass
class MonitoringPair:
    """Пара для мониторинга"""
    chain: str
    pair_address: str
    name: str
    expected_price: float = 1.0

@dataclass
class Config:
    """Конфигурация приложения"""
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")
    
    # Redis
    redis_host: str = os.getenv("REDIS_HOST", "redis")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    redis_channel: str = os.getenv("REDIS_CHANNEL", "depeg_alerts")
    
    # Monitoring
    check_interval: int = int(os.getenv("CHECK_INTERVAL", 30))
    depeg_threshold: float = float(os.getenv("DEPEG_THRESHOLD", 2.0))
    
    # API
    dexscreener_api_url: str = os.getenv(
        "DEXSCREENER_API_URL",
        "https://api.dexscreener.com/latest/dex"
    )
    
    # Пары для мониторинга
    monitoring_pairs: List[MonitoringPair] = None
    
    def __post_init__(self):
        if self.monitoring_pairs is None:
            # Примеры пар для мониторинга
            self.monitoring_pairs = [
                MonitoringPair(
                        chain="Ethereum",
                        pair_address="0x3416cf6c708da44db2624d63ea0aaef7113527c6",
                        name="USDC/USDT"
                    ),
            ]

config = Config()
