import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from depeg_bot.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=config.bot_token)
router = Router()
dp = Dispatcher()
dp.include_router(router)

redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    global redis_client
    redis_client = await aioredis.from_url(
        f"redis://{config.redis_host}:{config.redis_port}",
        encoding="utf-8",
        decode_responses=True,
    )


async def add_subscriber(user_id: int):
    return await redis_client.sadd("subscribers", str(user_id))


async def remove_subscriber(user_id: int):
    return await redis_client.srem("subscribers", str(user_id))


async def get_subscribers():
    return await redis_client.smembers("subscribers")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Subscribe the current Telegram user to depeg alerts."""

    user_id = message.from_user.id
    await add_subscriber(user_id)

    await message.answer(
        "🟢 <b>Monitor active</b>\n\n"
        "You are subscribed to stablecoin depeg alerts.\n"
        f"Alert threshold: {config.depeg_threshold}%\n\n"
        "Commands:\n"
        "/start - Subscribe to alerts\n"
        "/stop - Unsubscribe from alerts\n"
        "/status - Monitoring status\n"
        "/ping - Health check",
        parse_mode="HTML",
    )
    logger.info("User %s subscribed to alerts", user_id)


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    """Unsubscribe the current Telegram user from depeg alerts."""

    user_id = message.from_user.id
    if await remove_subscriber(user_id):
        await message.answer("🔴 You have unsubscribed from alerts")
        logger.info("User %s unsubscribed from alerts", user_id)
    else:
        await message.answer("You were not subscribed to alerts")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Show the current monitoring status."""

    subscribers = await get_subscribers()
    status_text = (
        "📊 <b>Monitoring status</b>\n\n"
        f"Subscribers: {len(subscribers)}\n"
        f"Depeg threshold: {config.depeg_threshold}%\n"
        f"Check interval: {config.check_interval}s\n"
        f"Tracked pairs: {len(config.monitoring_pairs)}\n\n"
        "<b>Pairs:</b>\n"
    )

    for pair in config.monitoring_pairs:
        status_text += f"• {pair.name} ({pair.chain})\n"

    await message.answer(status_text, parse_mode="HTML")


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    """Run a lightweight bot health check."""

    try:
        redis_status = "✅ OK" if redis_client and await redis_client.ping() else "❌ Disconnected"
    except Exception:
        redis_status = "❌ Error"

    eet_tz = timezone(timedelta(hours=2))
    current_time = datetime.now(eet_tz)

    uptime_text = "🟢 Bot is running\n\n"
    uptime_text += f"Redis: {redis_status}\n"
    uptime_text += f"Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')} EET\n\n"
    uptime_text += "All systems are operational ✅"

    await message.answer(uptime_text)
    logger.info("Ping command received from user %s", message.from_user.id)


async def format_alert_message(alert_data: dict) -> str:
    """Format a depeg alert for Telegram."""

    direction = "⬆️" if alert_data["current_price"] > alert_data["expected_price"] else "⬇️"
    dex_url = f"https://dexscreener.com/{alert_data['chain']}/{alert_data['pair_address']}"

    return (
        "🚨 <b>DEPEG ALERT</b> 🚨\n\n"
        f"<b>Pair:</b> {alert_data['pair_name']}\n"
        f"<b>Chain:</b> {alert_data['chain']}\n"
        f"<b>Price:</b> ${alert_data['current_price']:.6f}\n"
        f"<b>Expected:</b> ${alert_data['expected_price']:.2f}\n"
        f"<b>Deviation:</b> {direction} {alert_data['deviation']:.2f}%\n"
        f"<b>Time:</b> {alert_data['timestamp']}\n\n"
        f"📊 <a href='{dex_url}'>Open on DEX Screener</a>"
    )


async def redis_listener() -> None:
    """Listen for depeg alerts published by the watcher."""

    listener_client = await aioredis.from_url(
        f"redis://{config.redis_host}:{config.redis_port}",
        encoding="utf-8",
        decode_responses=True,
    )

    pubsub = listener_client.pubsub()
    await pubsub.subscribe(config.redis_channel)
    logger.info("Subscribed to Redis channel: %s", config.redis_channel)

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

            if message is not None and message["type"] == "message":
                try:
                    alert_data = json.loads(message["data"])
                    alert_message = await format_alert_message(alert_data)

                    subscribers = await get_subscribers()
                    logger.info("Sending alert to %s subscribers", len(subscribers))

                    for user_id in subscribers:
                        try:
                            await bot.send_message(
                                int(user_id),
                                alert_message,
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                            )
                            logger.info("Alert sent to %s", user_id)
                        except Exception as error:
                            logger.error("Error sending message to %s: %s", user_id, error)

                except json.JSONDecodeError:
                    logger.error("Failed to decode alert message")
                except Exception as error:
                    logger.error("Error processing alert: %s", error)

            await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        logger.info("Redis listener cancelled")
    finally:
        await pubsub.unsubscribe(config.redis_channel)
        await pubsub.close()
        await listener_client.close()


async def main() -> None:
    logger.info("Telegram bot starting...")
    logger.info("Monitor active")

    await init_redis()
    asyncio.create_task(redis_listener())

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if redis_client:
            await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())

