import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message
from config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота и роутера
bot = Bot(token=config.bot_token)
router = Router()
dp = Dispatcher()
dp.include_router(router)

# После инициализации бота
redis_client: Optional[aioredis.Redis] = None

async def init_redis():
    global redis_client
    redis_client = await aioredis.from_url(
        f"redis://{config.redis_host}:{config.redis_port}",
        encoding="utf-8",
        decode_responses=True
    )

async def add_subscriber(user_id: int):
    return await redis_client.sadd("subscribers", str(user_id))

async def remove_subscriber(user_id: int):
    return await redis_client.srem("subscribers", str(user_id))

async def get_subscribers():
    return await redis_client.smembers("subscribers")


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обрабочик команды /start"""
    user_id = message.from_user.id
    await add_subscriber(user_id)
    
    await message.answer(
        "🟢 <b>Monitor active</b>\n\n"
        "Вы подписаны на алерты о депеге стейблкоинов.\n"
        f"Порог срабатывания: {config.depeg_threshold}%\n\n"
        "Комады:\n"
        "/start - Подписаться на алерты\n"
        "/stop - Отписаться от алертов\n"
        "/status - Статус мониторинга",
        parse_mode="HTML"
    )
    logger.info(f"User {user_id} subscribed to alerts")


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    """Обработчик команды /stop"""
    user_id = message.from_user.id
    if await remove_subscriber(user_id):
        await message.answer("🔴 Вы отписались от алертов")
        logger.info(f"User {user_id} unsubscribed from alerts")
    else:
        await message.answer("Вы не были подписаны на алерты")


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Обработчик команды /status"""
    subscribers = await get_subscribers()
    status_text = (
        f"📊 <b>Статус мониторинга</b>\n\n"
        f"Подписчиков: {len(subscribers)}\n"
        f"Порог депега: {config.depeg_threshold}%\n"
        f"Интервал проверки: {config.check_interval}с\n"
        f"Отслеживаемых пар: {len(config.monitoring_pairs)}\n\n"
        f"<b>Пары:</b>\n"
    )
    
    for pair in config.monitoring_pairs:
        status_text += f"• {pair.name} ({pair.chain})\n"
    
    await message.answer(status_text, parse_mode="HTML")

@router.message(Command("ping"))
async def cmd_ping(message: Message):
    """Обработчик команды /ping - проверка работоспособности"""
    try:
        # Проверяем подключение к Redis
        redis_status = "✅ OK" if redis_client and await redis_client.ping() else "❌ Disconnected"
    except Exception:
        redis_status = "❌ Error"
    
    # Используем timezone-aware datetime для правильного времени
    from datetime import timezone, timedelta
    eet_tz = timezone(timedelta(hours=2))  # EET = UTC+2
    current_time = datetime.now(eet_tz)
    
    uptime_text = "🟢 Бот хорошо что работает\n\n"
    uptime_text += f"Redis: {redis_status}\n"
    uptime_text += f"Время: {current_time.strftime('%Y-%m-%d %H:%M:%S')} EET\n\n"
    uptime_text += "Все системы работают нормально! ✅"
    
    await message.answer(uptime_text)
    logger.info(f"Ping command received from user {message.from_user.id}")

async def format_alert_message(alert_data: dict) -> str:
    """Форматирование сообщения об алерте"""
    direction = "⬆️" if alert_data['current_price'] > alert_data['expected_price'] else "⬇️"
    
    # Формируем ссылку на DEX Screener
    dex_url = f"https://dexscreener.com/{alert_data['chain']}/{alert_data['pair_address']}"
    
    message = (
        f"🚨 <b>DEPEG ALERT</b> 🚨\n\n"
        f"<b>Пара:</b> {alert_data['pair_name']}\n"
        f"<b>Сеть:</b> {alert_data['chain']}\n"
        f"<b>Цена:</b> ${alert_data['current_price']:.6f}\n"
        f"<b>Ожидаемая:</b> ${alert_data['expected_price']:.2f}\n"
        f"<b>Отклонение:</b> {direction} {alert_data['deviation']:.2f}%\n"
        f"<b>Время:</b> {alert_data['timestamp']}\n\n"
        f"📊 <a href='{dex_url}'>Открыть на DEX Screener</a>"
    )
    
    return message


async def redis_listener():
    """Слушатель Redis Pub/Sub канала"""
    redis_client = await aioredis.from_url(
        f"redis://{config.redis_host}:{config.redis_port}",
        encoding="utf-8",
        decode_responses=True
    )
    
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(config.redis_channel)
    
    logger.info(f"📡 Subscribed to Redis channel: {config.redis_channel}")
    
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            
            if message is not None:
                logger.info(f"📨 Received message type: {message['type']}")
                
                if message['type'] == 'message':
                    try:
                        logger.info(f"📨 Message data: {message['data']}")
                        
                        alert_data = json.loads(message['data'])
                        alert_message = await format_alert_message(alert_data)
                        
                        # Отправка алерта всем подписанным пользователям
                        subscribers = await get_subscribers()
                        logger.info(f"👥 Subscribers count: {len(subscribers)}")
                        
                        for user_id in subscribers:
                            try:
                                await bot.send_message(
                                    int(user_id),
                                    alert_message,
                                    parse_mode="HTML",
                                    disable_web_page_preview=True  # ← ДОБАВЬ ЭТУ СТРОКУ
                                )
                                logger.info(f"✅ Alert sent to {user_id}")
                            except Exception as e:
                                logger.error(f"Error sending message to {user_id}: {e}")
                        
                        logger.info(f"Alert sent to {len(subscribers)} users")
                        
                    except json.JSONDecodeError:
                        logger.error("Failed to decode alert message")
                    except Exception as e:
                        logger.error(f"Error processing alert: {e}")
            
            await asyncio.sleep(0.01)
                    
    except asyncio.CancelledError:
        logger.info("Redis listener cancelled")
    finally:
        await pubsub.unsubscribe(config.redis_channel)
        await pubsub.close()
        await redis_client.close()



async def main():
    logger.info("🤖 Telegram Bot starting...")
    logger.info("Monitor active")
    
    # Инициализация Redis ПЕРЕД всем остальным
    await init_redis()
    
    # Запуск Redis listener в фоне
    asyncio.create_task(redis_listener())
    
    # Запуск бота
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if redis_client:
            await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())
