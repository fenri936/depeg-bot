import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import requests

MIN_LIQUIDITY = 5_000
DEXSCREENER_API = "https://api.dexscreener.com/token-pairs/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = PROJECT_ROOT / "data" / "pairs.json"
TEMP_FILE = PROJECT_ROOT / "data" / "pairs_temp.json"

BASE_DELAY = 0.5
RETRY_DELAY = 5
MAX_RETRIES = 3

CHAIN_QUOTE_TOKENS = {
    "ethereum": ["USDT", "USDC", "DAI", "WETH", "FRAX"],
    "arbitrum": ["USDC", "USDC.E", "USDT", "WETH", "DAI"],
    "optimism": ["USDC", "USDC.E", "USDT", "WETH", "DAI"],
    "base": ["USDC", "USDbC", "WETH"],
    "blast": ["USDB", "WETH"],
    "polygon": ["USDC", "USDC.E", "USDT", "WMATIC", "DAI"],
    "zksync": ["USDC", "USDT", "WETH"],
    "linea": ["USDC", "USDT", "WETH"],
    "scroll": ["USDC", "USDT", "WETH"],
    "mantle": ["USDC", "USDT", "WETH"],
    "mode": ["USDC", "WETH"],
    "bsc": ["USDT", "USDC", "BUSD", "WBNB", "DAI"],
    "avalanche": ["USDC", "USDC.E", "USDT", "USDT.E", "WAVAX", "DAI"],
    "fantom": ["USDC", "USDT", "DAI", "WFTM"],
    "cronos": ["USDC", "USDT", "DAI", "WCRO"],
    "gnosis": ["USDC", "WXDAI", "WETH"],
}

TOKEN_CATEGORIES = {
    "stablecoins": [
        "USDC",
        "USDT",
        "DAI",
        "BUSD",
        "FRAX",
        "TUSD",
        "USDP",
        "GUSD",
        "USDD",
        "PYUSD",
        "FDUSD",
        "crvUSD",
        "GHO",
        "LUSD",
        "DOLA",
        "alUSD",
        "MIM",
        "sUSD",
        "USDC.E",
        "USDC.e",
        "USDbC",
        "USDBC",
        "axlUSDC",
        "DAI.e",
        "FRAX.e",
        "USDT.e",
        "USDB",
        "cUSD",
        "WXDAI",
    ],
    "eth_wrappers": [
        "WETH",
        "ETH",
        "stETH",
        "wstETH",
        "rETH",
        "cbETH",
        "sfrxETH",
        "frxETH",
        "ankrETH",
        "swETH",
        "osETH",
        "ETHx",
        "mETH",
        "wBETH",
        "OETH",
        "sETH2",
        "rETH2",
        "aETH",
        "SETH",
    ],
    "btc_wrappers": [
        "WBTC",
        "tBTC",
        "renBTC",
        "sBTC",
        "cbBTC",
        "HBTC",
        "BTCB",
        "pBTC",
        "oBTC",
        "BBTC",
        "BTC.b",
        "WBTC.e",
        "tBTC.e",
    ],
}

TOKEN_FAMILIES = {
    "eth": TOKEN_CATEGORIES["eth_wrappers"],
    "btc": TOKEN_CATEGORIES["btc_wrappers"],
    "stable": TOKEN_CATEGORIES["stablecoins"],
}

SUPPORTED_CHAINS = [
    "ethereum",
    "arbitrum",
    "optimism",
    "base",
    "polygon",
    "zksync",
    "linea",
    "scroll",
    "mantle",
    "blast",
    "mode",
    "bsc",
    "avalanche",
    "fantom",
    "cronos",
    "gnosis",
]

MANUAL_CONTRACTS = {
    "linea": {
        "USDC": "0x176211869ca2b568f2a7d4ee941e073a821ee1ff",
        "USDT": "0xa219439258ca9da29e9cc4ce5596924745e12b93",
        "WETH": "0xe5d7c2a44ffddf6b295a15c148167daaaf5cf34f",
        "wstETH": "0xb5bedd42000b71fdde22d3ee8a79bd49a568fc8f",
    },
    "scroll": {
        "USDC": "0x06efdbff2a14a7c8e15944d1f4a48f9f95f663a4",
        "USDT": "0xf55bec9cafdbe8730f096aa55dad6d22d44099df",
        "WETH": "0x5300000000000000000000000000000000000004",
        "wstETH": "0xf610a9dfb7c89644979b4a0f27063e9e7d7cda32",
    },
    "mantle": {
        "USDC": "0x09bc4e0d864854c6afb6eb9a9cdf58ac190d0df9",
        "USDT": "0x201eba5cc46d216ce6dc03f6a759e8e766e956ae",
        "WETH": "0xdeaddeaddeaddeaddeaddeaddeaddeaddeaddead1111",
    },
    "blast": {
        "USDB": "0x4300000000000000000000000000000000000003",
        "WETH": "0x4300000000000000000000000000000000000004",
    },
    "mode": {
        "USDC": "0xd988097fb8612cc24eec14542bc03424c656005f",
        "WETH": "0x4200000000000000000000000000000000000006",
    },
}


def normalize_symbol(symbol: str) -> str:
    return symbol.upper()


def get_token_family(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    for family, tokens in TOKEN_FAMILIES.items():
        if normalized in [token.upper() for token in tokens]:
            return family
    return "unknown"


def is_quote_token(symbol: str, chain: str) -> bool:
    normalized = normalize_symbol(symbol)
    chain_quotes = CHAIN_QUOTE_TOKENS.get(chain.lower(), [])
    return normalized in [quote.upper() for quote in chain_quotes]


def classify_token(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    for category, tokens in TOKEN_CATEGORIES.items():
        if normalized in [token.upper() for token in tokens]:
            return category
    return "unknown"


def load_coingecko_tokens() -> List[Dict]:
    token_lists = [
        "https://tokens.coingecko.com/uniswap/all.json",
        "https://tokens.coingecko.com/arbitrum-one/all.json",
        "https://tokens.coingecko.com/optimistic-ethereum/all.json",
        "https://tokens.coingecko.com/base/all.json",
        "https://tokens.coingecko.com/polygon-pos/all.json",
    ]

    all_tokens = []

    for url in token_lists:
        try:
            chain_name = url.split("/")[-2]
            print(f"Loading {chain_name} tokens...")
            response = requests.get(url, timeout=20)
            if response.status_code == 200:
                tokens = response.json().get("tokens", [])
                all_tokens.extend(tokens)
                print(f"  OK: {len(tokens)} tokens")
                time.sleep(0.3)
        except Exception as error:
            print(f"  Failed: {error}")

    print(f"Loaded {len(all_tokens)} tokens from CoinGecko")
    return all_tokens


def load_1inch_tokens() -> Dict[str, List[Dict]]:
    chain_ids = {
        "1": "ethereum",
        "10": "optimism",
        "56": "bsc",
        "137": "polygon",
        "250": "fantom",
        "25": "cronos",
        "42161": "arbitrum",
        "43114": "avalanche",
        "8453": "base",
        "100": "gnosis",
        "324": "zksync",
    }

    all_tokens = {}

    print("\nLoading tokens from 1inch...")
    for chain_id, chain_name in chain_ids.items():
        try:
            url = f"https://tokens.1inch.io/v1.2/{chain_id}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                tokens = [
                    {
                        "symbol": token.get("symbol"),
                        "name": token.get("name"),
                        "address": address,
                        "chainId": int(chain_id),
                        "decimals": token.get("decimals"),
                    }
                    for address, token in response.json().items()
                ]
                all_tokens[chain_name] = tokens
                print(f"  OK: {chain_name}: {len(tokens)} tokens")
                time.sleep(0.5)
        except Exception as error:
            print(f"  Failed: {chain_name}: {error}")

    return all_tokens


def load_manual_contracts() -> Dict:
    print("\nAdding manual contracts...")

    contracts = defaultdict(lambda: defaultdict(list))

    for chain, tokens in MANUAL_CONTRACTS.items():
        for symbol, address in tokens.items():
            category = classify_token(symbol)
            if category == "unknown":
                continue

            contracts[chain][symbol].append(
                {
                    "address": address.lower(),
                    "category": category,
                    "is_quote": is_quote_token(symbol, chain),
                    "family": get_token_family(symbol),
                }
            )

        print(f"  OK: {chain}: {len(tokens)} tokens")

    return contracts


def extract_verified_contracts() -> Dict:
    print("\nExtracting verified contracts...\n")

    all_tokens = load_coingecko_tokens()
    oneinch_tokens = load_1inch_tokens()
    manual_contracts = load_manual_contracts()

    for chain_tokens in oneinch_tokens.values():
        all_tokens.extend(chain_tokens)

    print(f"\nTotal API tokens: {len(all_tokens)}")

    contracts = defaultdict(lambda: defaultdict(list))

    for chain, tokens in manual_contracts.items():
        for symbol, token_list in tokens.items():
            contracts[chain][symbol].extend(token_list)

    chain_id_map = {
        1: "ethereum",
        10: "optimism",
        25: "cronos",
        56: "bsc",
        100: "gnosis",
        137: "polygon",
        250: "fantom",
        324: "zksync",
        5000: "mantle",
        8453: "base",
        42161: "arbitrum",
        43114: "avalanche",
        59144: "linea",
        81457: "blast",
        534352: "scroll",
        34443: "mode",
    }

    for token in all_tokens:
        symbol = token.get("symbol", "").upper()
        chain_id = token.get("chainId")
        address = token.get("address", "").lower()

        if not symbol or not chain_id or not address:
            continue

        category = classify_token(symbol)
        if category == "unknown":
            continue

        chain_name = chain_id_map.get(chain_id)
        if not chain_name or chain_name not in SUPPORTED_CHAINS:
            continue

        contracts[chain_name][symbol].append(
            {
                "address": address,
                "category": category,
                "is_quote": is_quote_token(symbol, chain_name),
                "family": get_token_family(symbol),
            }
        )

    clean_contracts = {}
    for chain, tokens in contracts.items():
        clean_contracts[chain] = {}
        for symbol, token_list in tokens.items():
            quote_tokens = [token for token in token_list if token["is_quote"]]
            clean_contracts[chain][symbol] = quote_tokens[0] if quote_tokens else token_list[0]

    return clean_contracts


def fetch_token_pairs(chain: str, token_address: str, retry_count: int = 0) -> List[Dict]:
    url = f"{DEXSCREENER_API}/{chain}/{token_address}"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, list) else []

        if response.status_code == 429:
            if retry_count < MAX_RETRIES:
                wait_time = RETRY_DELAY * (2**retry_count)
                print(f"\n    Rate limit hit. Waiting {wait_time}s...", end="", flush=True)
                time.sleep(wait_time)
                print(" done")
                return fetch_token_pairs(chain, token_address, retry_count + 1)

            print("\n    Retry limit exceeded")
            return []

        return []

    except Exception:
        return []


def filter_pairs_by_quote(pairs: List[Dict], contracts: Dict, chain: str) -> List[Dict]:
    filtered = []
    seen_pairs = set()

    address_to_info = {}
    for symbol, token_data in contracts.get(chain, {}).items():
        address_to_info[token_data["address"].lower()] = {
            "symbol": symbol,
            "category": token_data["category"],
            "is_quote": token_data["is_quote"],
            "family": token_data["family"],
        }

    for pair in pairs:
        pair_address = pair.get("pairAddress", "")
        if pair_address in seen_pairs:
            continue

        liquidity_usd = pair.get("liquidity", {}).get("usd", 0)
        if liquidity_usd < MIN_LIQUIDITY:
            continue

        base_token = pair.get("baseToken", {})
        quote_token = pair.get("quoteToken", {})

        base_info = address_to_info.get(base_token.get("address", "").lower())
        quote_info = address_to_info.get(quote_token.get("address", "").lower())
        if not (base_info and quote_info):
            continue

        base_symbol = base_info["symbol"]
        quote_symbol = quote_info["symbol"]
        base_family = base_info["family"]
        quote_family = quote_info["family"]

        if not quote_info["is_quote"]:
            if base_info["is_quote"]:
                base_symbol, quote_symbol = quote_symbol, base_symbol
                base_family, quote_family = quote_family, base_family
            else:
                continue

        if base_family != quote_family:
            continue

        if base_family == quote_family == "stable":
            expected_price = 1.0
            pair_type = "stable/stable"
        elif base_family == quote_family == "eth":
            expected_price = 1.0
            pair_type = "eth/eth"
        elif base_family == quote_family == "btc":
            expected_price = 1.0
            pair_type = "btc/btc"
        else:
            expected_price = round(float(pair.get("priceNative", 1.0)), 6)
            pair_type = "other"

        seen_pairs.add(pair_address)
        filtered.append(
            {
                "chain": chain,
                "pair_address": pair_address,
                "name": f"{base_symbol}/{quote_symbol}",
                "expected_price": expected_price,
                "pair_type": pair_type,
                "dex": pair.get("dexId", ""),
                "liquidity_usd": round(liquidity_usd, 2),
                "base_symbol": base_symbol,
                "quote_symbol": quote_symbol,
            }
        )

    return filtered


def save_temp_results(pairs: List[Dict]) -> None:
    TEMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TEMP_FILE.open("w", encoding="utf-8") as file:
        json.dump(pairs, file, indent=2, ensure_ascii=False)


def main() -> None:
    print("Starting liquid pair discovery with same-family filtering...\n")

    contracts = extract_verified_contracts()

    print("\nContract statistics:")
    for chain, tokens in sorted(contracts.items()):
        quote_count = sum(1 for token in tokens.values() if token["is_quote"])
        total = len(tokens)
        if total > 0:
            print(f"  - {chain}: {total} tokens ({quote_count} quote tokens)")

    total_tokens = sum(len(tokens) for tokens in contracts.values())
    total_chains = len(contracts)
    print(f"\nTotal: {total_tokens} tokens across {total_chains} chains")

    print("\nSearching for base-asset pairs...")
    print(f"Request delay: {BASE_DELAY}s")
    print("Filter: same-family pairs only (ETH/ETH, BTC/BTC, stable/stable)\n")

    all_pairs = []
    total_requests = 0
    failed_requests = 0

    for chain_index, (chain, tokens) in enumerate(contracts.items(), 1):
        if not tokens:
            continue

        print(f"\n[{chain_index}/{total_chains}] {chain.upper()}")

        for token_index, (symbol, token_data) in enumerate(tokens.items(), 1):
            address = token_data["address"]
            progress = f"[{token_index}/{len(tokens)}]"
            print(f"  {progress} {symbol:12} ({address[:8]}...)", end="", flush=True)

            pairs = fetch_token_pairs(chain, address)
            total_requests += 1

            if pairs:
                print(f" OK: {len(pairs)} pairs")
                all_pairs.extend(pairs)
            elif pairs == []:
                print(" - no pairs")
            else:
                print(" failed")
                failed_requests += 1

            time.sleep(BASE_DELAY)

            if total_requests % 50 == 0:
                save_temp_results(all_pairs)
                print(f"\n  Temp save: {len(all_pairs)} pairs")

    print(f"\n\nTotal pairs found: {len(all_pairs)}")
    print(f"API requests: {total_requests} (errors: {failed_requests})\n")

    all_filtered = []
    for chain in contracts.keys():
        chain_pairs = [pair for pair in all_pairs if pair.get("chainId", "").lower() == chain]
        all_filtered.extend(filter_pairs_by_quote(chain_pairs, contracts, chain))

    print(f"Pairs after family filter: {len(all_filtered)}")

    unique_pairs = {}
    for pair in all_filtered:
        key = f"{pair['chain']}:{pair['pair_address']}"
        unique_pairs.setdefault(key, pair)

    final_pairs = list(unique_pairs.values())
    final_pairs.sort(key=lambda item: item["liquidity_usd"], reverse=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(final_pairs, file, indent=2, ensure_ascii=False)

    print(f"Unique pairs: {len(final_pairs)}")
    print(f"Saved to {OUTPUT_FILE}\n")

    chains_stats = defaultdict(int)
    quote_stats = defaultdict(int)
    pair_type_stats = defaultdict(int)

    for pair in final_pairs:
        chains_stats[pair["chain"]] += 1
        quote_stats[pair["quote_symbol"]] += 1
        pair_type_stats[pair["pair_type"]] += 1

    print("Top 10 chains:")
    for chain, count in sorted(chains_stats.items(), key=lambda item: item[1], reverse=True)[:10]:
        print(f"  - {chain}: {count} pairs")

    print("\nTop 10 quote tokens:")
    for quote, count in sorted(quote_stats.items(), key=lambda item: item[1], reverse=True)[:10]:
        print(f"  - {quote}: {count} pairs")

    print("\nPair types:")
    for pair_type, count in sorted(pair_type_stats.items()):
        print(f"  - {pair_type}: {count} pairs")

    print("\nTop 10 pairs by liquidity:")
    for index, pair in enumerate(final_pairs[:10], 1):
        print(f"  {index}. {pair['name']} ({pair['chain']}/{pair['dex']}) - ${pair['liquidity_usd']:,.0f}")

    print("\nDone.")
    print(f"Found {len(final_pairs)} pairs across {len(chains_stats)} chains")
    print("Contracts are sourced from public token lists plus manual verified entries")
    print("Only same-family pairs are included")


if __name__ == "__main__":
    main()

