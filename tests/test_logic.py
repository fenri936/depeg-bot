import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, User

os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

from depeg_bot import telegram_bot


@pytest.fixture
def mock_message():
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
    with patch("depeg_bot.telegram_bot.add_subscriber", new_callable=AsyncMock) as mock_add:
        await telegram_bot.cmd_start(mock_message)

        mock_add.assert_called_once_with(123456)
        mock_message.answer.assert_called_once()
        assert "Monitor active" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_stop_success(mock_message):
    with patch("depeg_bot.telegram_bot.remove_subscriber", new_callable=AsyncMock) as mock_remove:
        mock_remove.return_value = 1

        await telegram_bot.cmd_stop(mock_message)

        mock_remove.assert_called_once_with(123456)
        mock_message.answer.assert_called_once()
        assert "unsubscribed" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_stop_not_subscribed(mock_message):
    with patch("depeg_bot.telegram_bot.remove_subscriber", new_callable=AsyncMock) as mock_remove:
        mock_remove.return_value = 0

        await telegram_bot.cmd_stop(mock_message)

        mock_message.answer.assert_called_once()
        assert "not subscribed" in mock_message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_status(mock_message):
    with patch("depeg_bot.telegram_bot.get_subscribers", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"111", "222"}

        await telegram_bot.cmd_status(mock_message)

        mock_message.answer.assert_called_once()
        text = mock_message.answer.call_args[0][0]
        assert "Subscribers: 2" in text
        assert "Monitoring status" in text


@pytest.mark.asyncio
async def test_cmd_ping(mock_message):
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True

    with patch("depeg_bot.telegram_bot.redis_client", mock_redis):
        await telegram_bot.cmd_ping(mock_message)

        mock_message.answer.assert_called_once()
        text = mock_message.answer.call_args[0][0]
        assert "Redis: ✅ OK" in text
        assert "EET" in text

