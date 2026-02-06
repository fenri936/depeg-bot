import json
import time
import requests
from typing import Dict, List, Set
from collections import defaultdict

# Конфигурация
MIN_LIQUIDITY = 50000
DEXSCREENER_API = "https://api.dexscreener.com/token-pairs/v1"
OUTPUT_FILE = "pairs.json"
TEMP_FILE = "pairs_temp.json"

BASE_DELAY = 0.5
RETRY_DELAY = 5
MAX_RETRIES = 3

# 💎 Базовые ликвидные активы (quote токены)
QUOTE_TOKENS = [
    'USDT', 'USDC', 'USDC.E', 'USDbC', 'USDBC',
    'WETH', 'ETH',  # Только ETH для ETH-оберток
    'DAI', 'BUSD', 'FRAX'
]

# 🪙 ПРАВИЛЬНЫЕ категории - разделяем по БАЗОВОМУ активу
TOKEN_CATEGORIES = {
    'stablecoins': [
        'USDC', 'USDT', 'DAI', 'BUSD', 'FRAX', 'TUSD', 'USDP',
        'GUSD', 'USDD', 'PYUSD', 'FDUSD', 'crvUSD', 'GHO', 'LUSD',
        'DOLA', 'alUSD', 'MIM', 'sUSD', 'USDJ', 'USDN',
        'FEI', 'HUSD', 'OUSD', 'USDX', 'USDK', 'VAI',
        'CUSD', 'DUSD', 'agEUR', 'EURT', 'EURS', 'EURI',
        'USDC.E', 'USDC.e', 'USDbC', 'USDBC', 'axlUSDC', 'ceUSDC',
        'DAI.e', 'FRAX.e', 'USDT.e', 'axlDAI', 'axlUSDT'
    ],
    
    # ⚠️ ТОЛЬКО ETH обертки (НЕ включаем BNB, MATIC и т.д.!)
    'eth_wrappers': [
        'WETH', 'ETH',
        'stETH', 'wstETH', 'rETH', 'cbETH', 
        'sfrxETH', 'frxETH', 'ankrETH', 'swETH', 
        'osETH', 'ETHx', 'mETH', 'wBETH',
        'OETH', 'sETH2', 'rETH2', 'aETH', 'SETH'
    ],
    
    'btc_wrappers': [
        'WBTC', 'tBTC', 'renBTC', 'sBTC', 'cbBTC', 'HBTC',
        'BTCB', 'pBTC', 'oBTC', 'BBTC',
        'BTC.b', 'WBTC.e', 'tBTC.e'
    ]
}

# Семьи токенов - для проверки совместимости
TOKEN_FAMILIES = {
    'eth': ['WETH', 'ETH', 'stETH', 'wstETH', 'rETH', 'cbETH', 'sfrxETH', 'frxETH', 'ankrETH', 'swETH', 'osETH', 'ETHx', 'mETH', 'wBETH', 'OETH', 'sETH2', 'rETH2', 'aETH', 'SETH'],
    'btc': ['WBTC', 'tBTC', 'renBTC', 'sBTC', 'cbBTC', 'HBTC', 'BTCB', 'pBTC', 'oBTC', 'BBTC', 'BTC.b', 'WBTC.e', 'tBTC.e'],
    'stable': ['USDC', 'USDT', 'DAI', 'BUSD', 'FRAX', 'TUSD', 'USDP', 'GUSD', 'USDD', 'PYUSD', 'FDUSD', 'crvUSD', 'GHO', 'LUSD', 'DOLA', 'alUSD', 'MIM', 'sUSD', 'USDJ', 'USDN', 'FEI', 'HUSD', 'OUSD', 'USDX', 'USDK', 'VAI', 'CUSD', 'DUSD', 'agEUR', 'EURT', 'EURS', 'EURI', 'USDC.E', 'USDC.e', 'USDbC', 'USDBC', 'axlUSDC', 'ceUSDC', 'DAI.e', 'FRAX.e', 'USDT.e', 'axlDAI', 'axlUSDT']
}

SUPPORTED_CHAINS = [
    'ethereum', 'arbitrum', 'optimism', 'base', 'polygon', 'zksync',
    'linea', 'scroll', 'mantle', 'blast', 'mode',
    'bsc', 'avalanche', 'fantom', 'cronos', 'gnosis'
]


def get_token_family(symbol: str) -> str:
    """Определение семьи токена"""
    symbol = symbol.upper()
    for family, tokens in TOKEN_FAMILIES.items():
        if symbol in [t.upper() for t in tokens]:
            return family
    return 'unknown'


def load_coingecko_tokens() -> List[Dict]:
    """Загрузка токенов из CoinGecko token list"""
    url = "https://tokens.coingecko.com/uniswap/all.json"
    
    try:
        print("📥 Загружаю CoinGecko token list...")
        response = requests.get(url, timeout=20)
        if response.status_code == 200:
            data = response.json()
            tokens = data.get('tokens', [])
            print(f"✅ Загружено {len(tokens)} токенов от CoinGecko")
            return tokens
        else:
            print(f"⚠️ CoinGecko вернул статус {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Ошибка загрузки CoinGecko: {e}")
        return []


def load_1inch_tokens() -> Dict[str, List[Dict]]:
    """Загрузка токенов из 1inch для разных сетей"""
    chain_ids = {
        '1': 'ethereum',
        '10': 'optimism',
        '56': 'bsc',
        '137': 'polygon',
        '250': 'fantom',
        '42161': 'arbitrum',
        '43114': 'avalanche',
        '8453': 'base',
        '100': 'gnosis',
        '324': 'zksync'
    }
    
    all_tokens = {}
    
    for chain_id, chain_name in chain_ids.items():
        try:
            url = f"https://tokens.1inch.io/v1.2/{chain_id}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                tokens_data = response.json()
                tokens = []
                for address, token in tokens_data.items():
                    tokens.append({
                        'symbol': token.get('symbol'),
                        'name': token.get('name'),
                        'address': address,
                        'chainId': int(chain_id),
                        'decimals': token.get('decimals')
                    })
                all_tokens[chain_name] = tokens
                print(f"  ✓ {chain_name}: {len(tokens)} токенов")
                time.sleep(0.5)
        except Exception as e:
            print(f"  ✗ {chain_name}: {e}")
    
    return all_tokens


def classify_token(symbol: str) -> str:
    """Определение категории токена"""
    symbol = symbol.upper()
    
    for category, tokens in TOKEN_CATEGORIES.items():
        if symbol in [t.upper() for t in tokens]:
            return category
    
    return 'unknown'


def is_quote_token(symbol: str) -> bool:
    """Является ли токен базовым ликвидным активом (quote)"""
    return symbol.upper() in [q.upper() for q in QUOTE_TOKENS]


def extract_verified_contracts() -> Dict:
    """Извлечение всех верифицированных контрактов"""
    print("\n🔍 Извлекаю верифицированные контракты...\n")
    
    coingecko_tokens = load_coingecko_tokens()
    
    print("\n📥 Загружаю токены от 1inch...")
    oneinch_tokens = load_1inch_tokens()
    
    all_tokens = []
    all_tokens.extend(coingecko_tokens)
    
    for chain_tokens in oneinch_tokens.values():
        all_tokens.extend(chain_tokens)
    
    print(f"\n📊 Всего токенов из всех источников: {len(all_tokens)}")
    
    contracts = defaultdict(lambda: defaultdict(list))
    
    chain_id_map = {
        1: 'ethereum', 10: 'optimism', 25: 'cronos', 56: 'bsc',
        100: 'gnosis', 137: 'polygon', 250: 'fantom', 324: 'zksync',
        5000: 'mantle', 8453: 'base', 42161: 'arbitrum',
        43114: 'avalanche', 59144: 'linea', 81457: 'blast', 534352: 'scroll',
    }
    
    for token in all_tokens:
        symbol = token.get('symbol', '').upper()
        chain_id = token.get('chainId')
        address = token.get('address', '').lower()
        
        if not symbol or not chain_id or not address:
            continue
        
        category = classify_token(symbol)
        if category == 'unknown':
            continue
        
        chain_name = chain_id_map.get(chain_id)
        if not chain_name or chain_name not in SUPPORTED_CHAINS:
            continue
        
        contracts[chain_name][symbol].append({
            'address': address,
            'category': category,
            'is_quote': is_quote_token(symbol),
            'family': get_token_family(symbol)
        })
    
    clean_contracts = {}
    for chain, tokens in contracts.items():
        clean_contracts[chain] = {}
        for symbol, token_list in tokens.items():
            quote_tokens = [t for t in token_list if t['is_quote']]
            if quote_tokens:
                clean_contracts[chain][symbol] = quote_tokens[0]
            else:
                clean_contracts[chain][symbol] = token_list[0]
    
    return clean_contracts


def fetch_token_pairs(chain: str, token_address: str, retry_count: int = 0) -> List[Dict]:
    """Получение пар для контракта с обработкой rate limit"""
    url = f"{DEXSCREENER_API}/{chain}/{token_address}"
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, list) else []
        
        elif response.status_code == 429:
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_DELAY * (2 ** retry_count)
                print(f"\n    ⚠️ Rate limit! Жду {wait_time} сек...", end='', flush=True)
                time.sleep(wait_time)
                print(" ✓")
                return fetch_token_pairs(chain, token_address, retry_count + 1)
            else:
                print(f"\n    ❌ Превышен лимит попыток")
                return []
        else:
            return []
            
    except Exception as e:
        return []


def filter_pairs_by_quote(pairs: List[Dict], contracts: Dict, chain: str) -> List[Dict]:
    """Фильтрация: только пары одной семьи + quote токены"""
    filtered = []
    seen_pairs = set()
    
    chain_contracts = contracts.get(chain, {})
    
    address_to_info = {}
    for symbol, token_data in chain_contracts.items():
        address_to_info[token_data['address'].lower()] = {
            'symbol': symbol,
            'category': token_data['category'],
            'is_quote': token_data['is_quote'],
            'family': token_data['family']
        }
    
    for pair in pairs:
        pair_address = pair.get('pairAddress', '')
        
        if pair_address in seen_pairs:
            continue
        
        liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
        if liquidity_usd < MIN_LIQUIDITY:
            continue
        
        base_token = pair.get('baseToken', {})
        quote_token = pair.get('quoteToken', {})
        
        base_address = base_token.get('address', '').lower()
        quote_address = quote_token.get('address', '').lower()
        
        base_info = address_to_info.get(base_address)
        quote_info = address_to_info.get(quote_address)
        
        if not (base_info and quote_info):
            continue
        
        base_symbol = base_info['symbol']
        quote_symbol = quote_info['symbol']
        base_category = base_info['category']
        quote_category = quote_info['category']
        base_family = base_info['family']
        quote_family = quote_info['family']
        
        # ✅ Quote токен должен быть базовым ликвидным активом
        if not quote_info['is_quote']:
            if base_info['is_quote']:
                base_symbol, quote_symbol = quote_symbol, base_symbol
                base_category, quote_category = quote_category, base_category
                base_family, quote_family = quote_family, base_family
            else:
                continue
        
        # 🎯 КРИТИЧНО: Проверяем совместимость семей
        # Разрешены только пары из ОДНОЙ семьи
        if base_family != quote_family:
            # Исключаем кросс-чейн пары: ETH/BNB, ETH/MATIC, BTC/ETH и т.д.
            continue
        
        # 🎯 РАСЧЕТ EXPECTED_PRICE
        if base_family == 'stable' and quote_family == 'stable':
            expected_price = 1.0
            pair_type = 'stable/stable'
        elif base_family == 'eth' and quote_family == 'eth':
            expected_price = 1.0
            pair_type = 'eth/eth'
        elif base_family == 'btc' and quote_family == 'btc':
            expected_price = 1.0
            pair_type = 'btc/btc'
        else:
            # Не должны сюда попасть, но на всякий случай
            current_price = float(pair.get('priceNative', 1.0))
            expected_price = round(current_price, 6)
            pair_type = 'other'
        
        dex = pair.get('dexId', '')
        
        seen_pairs.add(pair_address)
        
        filtered.append({
            'chain': chain,
            'pair_address': pair_address,
            'name': f"{base_symbol}/{quote_symbol}",
            'expected_price': expected_price,
            'pair_type': pair_type,
            'dex': dex,
            'liquidity_usd': round(liquidity_usd, 2),
            'base_symbol': base_symbol,
            'quote_symbol': quote_symbol
        })
    
    return filtered


def save_temp_results(pairs: List[Dict]):
    """Сохранение промежуточных результатов"""
    with open(TEMP_FILE, 'w', encoding='utf-8') as f:
        json.dump(pairs, f, indent=2, ensure_ascii=False)


def main():
    print("🚀 Автоматический поиск ликвидных пар (ФИЛЬТР ПО СЕМЬЯМ)...\n")
    
    contracts = extract_verified_contracts()
    
    print("\n📊 Статистика по контрактам:")
    for chain, tokens in sorted(contracts.items()):
        quote_count = sum(1 for t in tokens.values() if t['is_quote'])
        total = len(tokens)
        if total > 0:
            print(f"  • {chain}: {total} токенов ({quote_count} quote)")
    
    total_tokens = sum(len(tokens) for tokens in contracts.values())
    total_chains = len(contracts)
    print(f"\n🎯 Итого: {total_tokens} токенов в {total_chains} сетях")
    
    print("\n🔍 Ищу пары с базовыми активами...")
    print(f"⏱️ Задержка между запросами: {BASE_DELAY} сек")
    print("🔒 Фильтр: только пары одной семьи (ETH/ETH, BTC/BTC, stable/stable)\n")
    
    all_pairs = []
    total_requests = 0
    failed_requests = 0
    
    for chain_idx, (chain, tokens) in enumerate(contracts.items(), 1):
        if not tokens:
            continue
        
        print(f"\n[{chain_idx}/{total_chains}] 📡 {chain.upper()}")
        
        for token_idx, (symbol, token_data) in enumerate(tokens.items(), 1):
            address = token_data['address']
            
            progress = f"[{token_idx}/{len(tokens)}]"
            print(f"  {progress} {symbol:12} ({address[:8]}...)", end='', flush=True)
            
            pairs = fetch_token_pairs(chain, address)
            total_requests += 1
            
            if pairs:
                print(f" ✓ {len(pairs)} пар")
                all_pairs.extend(pairs)
            elif pairs == []:
                print(" - нет пар")
            else:
                print(" ✗ ошибка")
                failed_requests += 1
            
            time.sleep(BASE_DELAY)
            
            if total_requests % 50 == 0:
                save_temp_results(all_pairs)
                print(f"\n  💾 Промежуточное сохранение ({len(all_pairs)} пар)")
    
    print(f"\n\n📊 Всего найдено: {len(all_pairs)} пар")
    print(f"📡 Запросов к API: {total_requests} (ошибок: {failed_requests})\n")
    
    all_filtered = []
    for chain in contracts.keys():
        chain_pairs = [p for p in all_pairs if p.get('chainId', '').lower() == chain]
        filtered = filter_pairs_by_quote(chain_pairs, contracts, chain)
        all_filtered.extend(filtered)
    
    print(f"✅ Пар после фильтра семей: {len(all_filtered)}")
    
    unique_pairs = {}
    for pair in all_filtered:
        key = f"{pair['chain']}:{pair['pair_address']}"
        if key not in unique_pairs:
            unique_pairs[key] = pair
    
    final_pairs = list(unique_pairs.values())
    print(f"🎯 Уникальных пар: {len(final_pairs)}")
    
    final_pairs.sort(key=lambda x: x['liquidity_usd'], reverse=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_pairs, f, indent=2, ensure_ascii=False)
    
    print(f"💾 Сохранено в {OUTPUT_FILE}\n")
    
    print("📈 Статистика:")
    
    chains_stats = defaultdict(int)
    quote_stats = defaultdict(int)
    pair_type_stats = defaultdict(int)
    
    for pair in final_pairs:
        chains_stats[pair['chain']] += 1
        quote_stats[pair['quote_symbol']] += 1
        pair_type_stats[pair['pair_type']] += 1
    
    print("\n🌐 Топ-10 сетей:")
    for chain, count in sorted(chains_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  • {chain}: {count} пар")
    
    print("\n💎 Топ-10 quote токенов:")
    for quote, count in sorted(quote_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  • {quote}: {count} пар")
    
    print("\n📊 По типу пар:")
    for ptype, count in sorted(pair_type_stats.items()):
        print(f"  • {ptype}: {count} пар")
    
    print("\n🏆 Топ-10 пар по ликвидности:")
    for i, pair in enumerate(final_pairs[:10], 1):
        print(f"  {i}. {pair['name']} ({pair['chain']}/{pair['dex']}) - ${pair['liquidity_usd']:,.0f}")
    
    print("\n✅ Готово!")
    print(f"🎯 Найдено {len(final_pairs)} пар в {len(chains_stats)} сетях")
    print("🔐 100% верифицированные контракты")
    print("🔒 Только пары одной семьи (без кросс-чейн)")


if __name__ == "__main__":
    main()
