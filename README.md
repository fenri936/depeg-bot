# Depeg Bot

Telegram bot that monitors stablecoin, ETH-wrapper, and BTC-wrapper liquidity pairs on DEX Screener and sends alerts when a pair deviates from its expected peg.

## Features

- Watches configured DEX pairs from `data/pairs.json`
- Publishes depeg events through Redis
- Sends Telegram alerts to subscribed users
- Supports `/start`, `/stop`, `/status`, and `/ping`
- Includes a pair discovery script for refreshing the monitored pair list
- Ships with Docker Compose for local or server deployment

## Project Structure

```text
.
├── data/
│   └── pairs.json
├── scripts/
│   └── update_pairs.py
├── src/
│   └── depeg_bot/
│       ├── config.py
│       ├── price_watcher.py
│       └── telegram_bot.py
├── tests/
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Requirements

- Python 3.11+
- Redis
- Telegram bot token from BotFather
- Docker and Docker Compose for containerized deployment

## Configuration

Create a local `.env` file from the example:

```bash
cp .env.example .env
```

Environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | empty | Telegram bot token |
| `REDIS_HOST` | `redis` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_CHANNEL` | `depeg_alerts` | Redis Pub/Sub channel for alerts |
| `CHECK_INTERVAL` | `30` | Delay between monitoring cycles in seconds |
| `DEPEG_THRESHOLD` | `2.0` | Percent deviation required to trigger an alert |
| `DEXSCREENER_API_URL` | `https://api.dexscreener.com/latest/dex` | DexScreener pair API base URL |
| `MONITORING_PAIRS_FILE` | `data/pairs.json` | Path to monitored pairs JSON |

## Run With Docker

```bash
docker compose up -d --build
```

The compose stack starts Redis, the price watcher, and the Telegram bot.

## Run Locally

Install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Start Redis locally, then run the two app processes:

```bash
$env:PYTHONPATH = "src"
python -m depeg_bot.price_watcher
python -m depeg_bot.telegram_bot
```

## Refresh Monitored Pairs

```bash
$env:PYTHONPATH = "src"
python scripts/update_pairs.py
```

The script loads verified token lists, filters same-family pairs, sorts by liquidity, and writes the result to `data/pairs.json`.

## Tests

```bash
pytest
```

## Security Notes

- Do not commit `.env` or real Telegram tokens.
- Store production values in GitHub Actions secrets.
- If a token was committed before, rotate it before making the repository public.

