import os
import json
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class MonitoringPair:
    """Пара для мониторинга"""
    chain: str
    pair_address: str
    name: str
    expected_price: float = 1.0
    pair_type: str = 'stable/stable'  

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
            self.monitoring_pairs = self._load_pairs_from_json()
    
    def _load_pairs_from_json(self) -> List[MonitoringPair]:
        """Загрузка пар из pairs.json"""
        pairs_file = "pairs.json"
        
        try:
            with open(pairs_file, 'r', encoding='utf-8') as f:
                pairs_data = json.load(f)
            
            pairs = [
                MonitoringPair(
                    chain=pair['chain'],
                    pair_address=pair['pair_address'],
                    name=pair['name'],
                    expected_price=pair.get('expected_price', 1.0),
                    pair_type=pair.get('pair_type', 'stable/stable')  # ← ЧИТАЕМ НОВОЕ ПОЛЕ
                )
                for pair in pairs_data
            ]
            
            print(f"✅ Загружено {len(pairs)} пар из {pairs_file}")
            return pairs
            
        except FileNotFoundError:
            print(f"⚠️ Файл {pairs_file} не найден!")
            print("ℹ️ Запусти: python fetch_liquid_pairs.py")
            return []
            
        except Exception as e:
            print(f"❌ Ошибка загрузки пар: {e}")
            return []

config = Config()
