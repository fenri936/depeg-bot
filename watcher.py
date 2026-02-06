import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional

import aiohttp
import redis.asyncio as aioredis
from config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DexScreenerWatcher:
    """Вотчер для мониторинга пар на DexScreener"""
    
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_prices: Dict[str, float] = {}
        
    async def connect_redis(self):
        """Подключение к Redis"""
        self.redis_client = await aioredis.from_url(
            f"redis://{config.redis_host}:{config.redis_port}",
            encoding="utf-8",
            decode_responses=True
        )
        logger.info("✓ Connected to Redis")
        
    async def fetch_pair_data(self, chain: str, pair_address: str) -> Optional[Dict]:
        """Получение данных пары с DexScreener API"""
        url = f"{config.dexscreener_api_url}/pairs/{chain}/{pair_address}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('pair') or (data.get('pairs') or [None])[0]
                else:
                    logger.warning(f"API returned status {response.status} for {chain}/{pair_address}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching pair data: {e}")
            return None
            
    def calculate_deviation(self, current_price: float, expected_price: float) -> float:
        """Расчет отклонения цены в процентах"""
        return abs((current_price - expected_price) / expected_price * 100)
        
    async def publish_alert(self, alert_data: Dict):
        """Публикация алерта в Redis канал"""
        try:
            message = json.dumps(alert_data)
            await self.redis_client.publish(config.redis_channel, message)
            logger.info(f"🚨 Alert published: {alert_data['pair_name']}")
        except Exception as e:
            logger.error(f"Error publishing alert: {e}")
            
    async def check_pair(self, pair):
        """Проверка одной пары на депег"""
        pair_data = await self.fetch_pair_data(pair.chain, pair.pair_address)
        
        if not pair_data:
            return
            
        try:
            current_price = float(pair_data.get('priceUsd', 0))
            
            if current_price == 0:
                logger.warning(f"Invalid price for {pair.name}")
                return
                
            deviation = self.calculate_deviation(current_price, pair.expected_price)
            
            pair_key = f"{pair.chain}:{pair.pair_address}"
            previous_price = self.last_prices.get(pair_key, pair.expected_price)
            self.last_prices[pair_key] = current_price
            
            logger.info(
                f"📊 {pair.name} ({pair.chain}): "
                f"${current_price:.4f} | Deviation: {deviation:.2f}%"
            )
            
            # Проверка на депег
            if deviation > config.depeg_threshold:
                alert_data = {
                    'pair_name': pair.name,
                    'chain': pair.chain,
                    'current_price': current_price,
                    'expected_price': pair.expected_price,
                    'deviation': round(deviation, 2),
                    'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
                    'pair_address': pair.pair_address
                }
                await self.publish_alert(alert_data)
                
        except (ValueError, KeyError) as e:
            logger.error(f"Error processing pair {pair.name}: {e}")
            
    async def monitor_loop(self):
        """Основной цикл мониторинга"""
        logger.info("🔍 Starting monitoring loop...")
        logger.info(f"Monitoring {len(config.monitoring_pairs)} pairs")
        logger.info(f"Check interval: {config.check_interval}s")
        logger.info(f"Depeg threshold: {config.depeg_threshold}%")
        
        while True:
            try:
                # Асинхронная проверка всех пар
                tasks = [self.check_pair(pair) for pair in config.monitoring_pairs]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                await asyncio.sleep(config.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)
                
    async def start(self):
        """Запуск вотчера"""
        await self.connect_redis()
        
        self.session = aiohttp.ClientSession()
        
        try:
            await self.monitor_loop()
        finally:
            await self.session.close()
            await self.redis_client.close()


async def main():
    logger.info("🚀 DexScreener Depeg Watcher starting...")
    watcher = DexScreenerWatcher()
    await watcher.start()


if __name__ == "__main__":
    asyncio.run(main())
