import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
import redis.asyncio as aioredis

from depeg_bot.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DexScreenerWatcher:
    """Monitor DEX pairs through the DexScreener API."""

    def __init__(self) -> None:
        self.redis_client: Optional[aioredis.Redis] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.price_history: Dict[str, list] = defaultdict(list)
        self.max_history_size = 10

        self.batch_size = 20
        self.batch_delay = 2
        self.request_delay = 0.1

    async def connect_redis(self) -> None:
        self.redis_client = await aioredis.from_url(
            f"redis://{config.redis_host}:{config.redis_port}",
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Connected to Redis")

    async def fetch_pair_data(
        self,
        chain: str,
        pair_address: str,
        retry_count: int = 0,
    ) -> Optional[Dict]:
        """Fetch pair data from DexScreener with basic rate-limit handling."""

        url = f"{config.dexscreener_api_url}/pairs/{chain}/{pair_address}"

        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("pair") or (data.get("pairs") or [None])[0]

                if response.status == 429:
                    if retry_count < 3:
                        wait_time = 5 * (2**retry_count)
                        logger.warning(
                            "Rate limit hit. Waiting %ss (retry %s/3)",
                            wait_time,
                            retry_count + 1,
                        )
                        await asyncio.sleep(wait_time)
                        return await self.fetch_pair_data(chain, pair_address, retry_count + 1)

                    logger.error("Max retries exceeded for %s/%s", chain, pair_address)
                    return None

                logger.warning("API returned status %s for %s/%s", response.status, chain, pair_address)
                return None

        except Exception as error:
            logger.error("Error fetching pair data: %s", error)
            return None

    def get_pair_type(self, pair) -> str:
        return getattr(pair, "pair_type", "stable/stable")

    def calculate_dynamic_expected_price(self, pair_key: str, current_price: float) -> float:
        history = self.price_history[pair_key]
        if len(history) < 3:
            return current_price

        return sum(history) / len(history)

    def update_price_history(self, pair_key: str, price: float) -> None:
        history = self.price_history[pair_key]
        history.append(price)

        if len(history) > self.max_history_size:
            history.pop(0)

    def calculate_deviation(self, current_price: float, expected_price: float) -> float:
        if expected_price == 0:
            return 0
        return abs((current_price - expected_price) / expected_price * 100)

    async def publish_alert(self, alert_data: Dict) -> None:
        try:
            message = json.dumps(alert_data)
            await self.redis_client.publish(config.redis_channel, message)
            logger.info("Alert published: %s", alert_data["pair_name"])
        except Exception as error:
            logger.error("Error publishing alert: %s", error)

    async def check_pair(self, pair) -> None:
        pair_data = await self.fetch_pair_data(pair.chain, pair.pair_address)
        if not pair_data:
            return

        try:
            current_price = float(pair_data.get("priceNative", 0))
            if current_price == 0:
                logger.warning("Invalid price for %s", pair.name)
                return

            pair_key = f"{pair.chain}:{pair.pair_address}"
            pair_type = self.get_pair_type(pair)

            if pair_type in {"stable/stable", "wrapper/wrapper", "eth/eth", "btc/btc"}:
                expected_price = pair.expected_price
            else:
                expected_price = self.calculate_dynamic_expected_price(pair_key, current_price)
                self.update_price_history(pair_key, current_price)

            deviation = self.calculate_deviation(current_price, expected_price)

            logger.info(
                "%s (%s): %.6f (expected %.6f), deviation %.2f%%, type %s",
                pair.name,
                pair.chain,
                current_price,
                expected_price,
                deviation,
                pair_type,
            )

            if deviation > config.depeg_threshold:
                alert_data = {
                    "pair_name": pair.name,
                    "chain": pair.chain,
                    "current_price": current_price,
                    "expected_price": expected_price,
                    "deviation": round(deviation, 2),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "pair_address": pair.pair_address,
                }
                await self.publish_alert(alert_data)

        except (ValueError, KeyError) as error:
            logger.error("Error processing pair %s: %s", pair.name, error)

    async def check_pairs_batch(self, pairs: List, batch_number: int, total_batches: int) -> None:
        logger.info("Batch %s/%s: checking %s pairs", batch_number, total_batches, len(pairs))

        for index, pair in enumerate(pairs):
            await self.check_pair(pair)

            if index < len(pairs) - 1:
                await asyncio.sleep(self.request_delay)

    async def monitor_loop(self) -> None:
        logger.info("Starting monitoring loop")
        logger.info("Monitoring %s pairs", len(config.monitoring_pairs))
        logger.info("Batch size: %s pairs", self.batch_size)
        logger.info("Batch delay: %ss", self.batch_delay)
        logger.info("Request delay: %ss", self.request_delay)
        logger.info("Check interval: %ss", config.check_interval)
        logger.info("Depeg threshold: %s%%", config.depeg_threshold)

        while True:
            try:
                pairs = config.monitoring_pairs
                total_batches = (len(pairs) + self.batch_size - 1) // self.batch_size

                logger.info("Starting new monitoring cycle (%s batches)", total_batches)

                for index in range(0, len(pairs), self.batch_size):
                    batch = pairs[index : index + self.batch_size]
                    batch_number = (index // self.batch_size) + 1

                    await self.check_pairs_batch(batch, batch_number, total_batches)

                    if index + self.batch_size < len(pairs):
                        logger.info("Waiting %ss before next batch", self.batch_delay)
                        await asyncio.sleep(self.batch_delay)

                logger.info("Monitoring cycle completed")
                logger.info("Sleeping %ss until next cycle", config.check_interval)
                await asyncio.sleep(config.check_interval)

            except Exception as error:
                logger.error("Error in monitoring loop: %s", error)
                await asyncio.sleep(5)

    async def start(self) -> None:
        await self.connect_redis()
        self.session = aiohttp.ClientSession()

        try:
            await self.monitor_loop()
        finally:
            await self.session.close()
            await self.redis_client.close()


async def main() -> None:
    logger.info("DexScreener depeg watcher starting...")
    watcher = DexScreenerWatcher()
    await watcher.start()


if __name__ == "__main__":
    asyncio.run(main())

