import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional, List
from collections import defaultdict

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
        # История цен: {pair_key: [price1, price2, ...]}
        self.price_history: Dict[str, list] = defaultdict(list)
        self.max_history_size = 10
        
        # Rate limit настройки
        self.batch_size = 20  # Проверять по 20 пар за раз
        self.batch_delay = 2  # 2 секунды между батчами
        self.request_delay = 0.1  # 0.1 сек между запросами в батче
        
    async def connect_redis(self):
        """Подключение к Redis"""
        self.redis_client = await aioredis.from_url(
            f"redis://{config.redis_host}:{config.redis_port}",
            encoding="utf-8",
            decode_responses=True
        )
        logger.info("✓ Connected to Redis")
        
    async def fetch_pair_data(self, chain: str, pair_address: str, retry_count: int = 0) -> Optional[Dict]:
        """Получение данных пары с DexScreener API с обработкой rate limit"""
        url = f"{config.dexscreener_api_url}/pairs/{chain}/{pair_address}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('pair') or (data.get('pairs') or [None])[0]
                
                elif response.status == 429:
                    # Rate limit
                    if retry_count < 3:
                        wait_time = 5 * (2 ** retry_count)  # 5, 10, 20 секунд
                        logger.warning(f"Rate limit hit! Waiting {wait_time}s... (retry {retry_count + 1}/3)")
                        await asyncio.sleep(wait_time)
                        return await self.fetch_pair_data(chain, pair_address, retry_count + 1)
                    else:
                        logger.error(f"Max retries exceeded for {chain}/{pair_address}")
                        return None
                else:
                    logger.warning(f"API returned status {response.status} for {chain}/{pair_address}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching pair data: {e}")
            return None
    
    def get_pair_type(self, pair) -> str:
        """Определение типа пары"""
        return getattr(pair, 'pair_type', 'stable/stable')
    
    def calculate_dynamic_expected_price(self, pair_key: str, current_price: float) -> float:
        """Расчет динамического expected_price на основе истории"""
        history = self.price_history[pair_key]
        
        if len(history) < 3:
            return current_price
        
        avg_price = sum(history) / len(history)
        return avg_price
    
    def update_price_history(self, pair_key: str, price: float):
        """Обновление истории цен"""
        history = self.price_history[pair_key]
        history.append(price)
        
        if len(history) > self.max_history_size:
            history.pop(0)
            
    def calculate_deviation(self, current_price: float, expected_price: float) -> float:
        """Расчет отклонения цены в процентах"""
        if expected_price == 0:
            return 0
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
            current_price = float(pair_data.get('priceNative', 0))
            
            if current_price == 0:
                logger.warning(f"Invalid price for {pair.name}")
                return
            
            pair_key = f"{pair.chain}:{pair.pair_address}"
            pair_type = self.get_pair_type(pair)
            
            # Логика в зависимости от типа пары
            if pair_type == 'stable/stable':
                expected_price = pair.expected_price
            elif pair_type == 'wrapper/wrapper':
                expected_price = pair.expected_price
            else:
                expected_price = self.calculate_dynamic_expected_price(pair_key, current_price)
                self.update_price_history(pair_key, current_price)
            
            deviation = self.calculate_deviation(current_price, expected_price)
            
            logger.info(
                f"📊 {pair.name} ({pair.chain}): "
                f"{current_price:.6f} (exp: {expected_price:.6f}) | "
                f"Dev: {deviation:.2f}% | Type: {pair_type}"
            )
            
            # Проверка на депег
            if deviation > config.depeg_threshold:
                alert_data = {
                    'pair_name': pair.name,
                    'chain': pair.chain,
                    'current_price': current_price,
                    'expected_price': expected_price,
                    'deviation': round(deviation, 2),
                    'timestamp': datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
                    'pair_address': pair.pair_address
                }
                await self.publish_alert(alert_data)
                
        except (ValueError, KeyError) as e:
            logger.error(f"Error processing pair {pair.name}: {e}")
    
    async def check_pairs_batch(self, pairs: List, batch_num: int, total_batches: int):
        """Проверка батча пар с задержкой между запросами"""
        logger.info(f"🔍 Batch {batch_num}/{total_batches}: checking {len(pairs)} pairs...")
        
        for i, pair in enumerate(pairs):
            await self.check_pair(pair)
            
            # Задержка между запросами в батче (кроме последнего)
            if i < len(pairs) - 1:
                await asyncio.sleep(self.request_delay)
    
    async def monitor_loop(self):
        """Основной цикл мониторинга с батчингом"""
        logger.info("🔍 Starting monitoring loop...")
        logger.info(f"Monitoring {len(config.monitoring_pairs)} pairs")
        logger.info(f"Batch size: {self.batch_size} pairs")
        logger.info(f"Batch delay: {self.batch_delay}s")
        logger.info(f"Request delay: {self.request_delay}s")
        logger.info(f"Check interval: {config.check_interval}s")
        logger.info(f"Depeg threshold: {config.depeg_threshold}%")
        
        while True:
            try:
                # Разбиваем пары на батчи
                pairs = config.monitoring_pairs
                total_batches = (len(pairs) + self.batch_size - 1) // self.batch_size
                
                logger.info(f"\n🔄 Starting new monitoring cycle ({total_batches} batches)")
                
                for i in range(0, len(pairs), self.batch_size):
                    batch = pairs[i:i + self.batch_size]
                    batch_num = (i // self.batch_size) + 1
                    
                    await self.check_pairs_batch(batch, batch_num, total_batches)
                    
                    # Задержка между батчами (кроме последнего)
                    if i + self.batch_size < len(pairs):
                        logger.info(f"⏸️ Waiting {self.batch_delay}s before next batch...")
                        await asyncio.sleep(self.batch_delay)
                
                logger.info(f"\n✅ Monitoring cycle completed")
                logger.info(f"⏸️ Sleeping {config.check_interval}s until next cycle...\n")
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
