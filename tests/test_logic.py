
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import Message, User, Chat

# Устанавливаем фейковый токен перед импортом бота, чтобы aiogram не ругался
os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

# Импортируем модуль бота
import bot

@pytest.fixture
def mock_message():
    """Фикстура для создания мок-объекта сообщения"""
    message = AsyncMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 123456
    message.from_user.first_name = "TestUser"
    message.chat = MagicMock(spec=Chat)
    message.chat.id = 123456
    message.answer = AsyncMock()
    return message

@pytest.mark.asyncio
async def test_cmd_start(mock_message):
    """Тест команды /start: должен добавить подписчика"""
    # Патчим функцию add_subscriber в модуле bot
    with patch('bot.add_subscriber', new_callable=AsyncMock) as mock_add:
        await bot.cmd_start(mock_message)
        
        # Проверяем, что add_subscriber был вызван с правильным ID
        mock_add.assert_called_once_with(123456)
        
        # Проверяем, что бот отправил ответ
        mock_message.answer.assert_called_once()
        assert "Monitor active" in mock_message.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_cmd_stop_success(mock_message):
    """Тест команды /stop: успешная отписка"""
    # Патчим remove_subscriber, имитируем что удаление прошло успешно (вернуло 1)
    with patch('bot.remove_subscriber', new_callable=AsyncMock) as mock_remove:
        mock_remove.return_value = 1
        
        await bot.cmd_stop(mock_message)
        
        mock_remove.assert_called_once_with(123456)
        mock_message.answer.assert_called_once()
        assert "отписались" in mock_message.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_cmd_stop_not_subscribed(mock_message):
    """Тест команды /stop: пользователь не был подписан"""
    # Имитируем, что удаление вернуло 0 (пользователя не было)
    with patch('bot.remove_subscriber', new_callable=AsyncMock) as mock_remove:
        mock_remove.return_value = 0
        
        await bot.cmd_stop(mock_message)
        
        mock_message.answer.assert_called_once()
        assert "не были подписаны" in mock_message.answer.call_args[0][0]

@pytest.mark.asyncio
async def test_cmd_status(mock_message):
    """Тест команды /status"""
    # Патчим get_subscribers, возвращаем множество из 2 ID
    with patch('bot.get_subscribers', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"111", "222"}
        
        await bot.cmd_status(mock_message)
        
        mock_message.answer.assert_called_once()
        text = mock_message.answer.call_args[0][0]
        assert "Подписчиков: 2" in text
        assert "Статус мониторинга" in text

@pytest.mark.asyncio
async def test_cmd_ping(mock_message):
    """Тест команды /ping"""
    # Создаем мок для redis_client
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    
    # Патчим redis_client внутри модуля bot
    with patch('bot.redis_client', mock_redis):
        await bot.cmd_ping(mock_message)
        
        mock_message.answer.assert_called_once()
        text = mock_message.answer.call_args[0][0]
        assert "Redis: ✅ OK" in text
        assert "EET" in text
