import json
import time
import requests
from typing import List, Dict

# Конфигурация
MIN_LIQUIDITY = 50000  # Минимальная ликвидность в USD
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"
TARGETS_FILE = "targets.json"
OUTPUT_FILE = "pairs.json"


def load_targets() -> List[str]:
    """Загрузка списка токенов из targets.json"""
    try:
        with open(TARGETS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Собираем все токены из всех категорий
        all_tokens = []
        for category, tokens in data.items():
            all_tokens.extend(tokens)
            print(f"📂 Категория '{category}': {len(tokens)} токенов")
        
        # Удаляем дубликаты
        unique_tokens = list(set(all_tokens))
        print(f"🎯 Уникальных токенов: {len(unique_tokens)}")
        return unique_tokens
        
    except FileNotFoundError:
        print(f"❌ Файл {TARGETS_FILE} не найден!")
        return []
    except Exception as e:
        print(f"❌ Ошибка чтения {TARGETS_FILE}: {e}")
        return []


def search_token_pairs(token: str) -> List[Dict]:
    """Поиск пар по токену через DexScreener API"""
    url = f"{DEXSCREENER_API}/search?q={token}"
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            pairs = data.get('pairs', [])
            print(f"  ✓ {token}: найдено {len(pairs)} пар")
            return pairs
        elif response.status_code == 429:
            print(f"  ⚠️ {token}: Rate limit! Жду 5 секунд...")
            time.sleep(5)
            return search_token_pairs(token)  # Повторяем запрос
        else:
            print(f"  ✗ {token}: статус {response.status_code}")
            return []
            
    except Exception as e:
        print(f"  ✗ {token}: ошибка {e}")
        return []


def filter_and_format_pairs(pairs: List[Dict]) -> List[Dict]:
    """Фильтрация и форматирование пар"""
    filtered = []
    
    for pair in pairs:
        # Проверка ликвидности
        liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
        if liquidity_usd < MIN_LIQUIDITY:
            continue
        
        # Получаем данные
        chain = pair.get('chainId', '').lower()
        pair_address = pair.get('pairAddress', '')
        base_symbol = pair.get('baseToken', {}).get('symbol', '')
        quote_symbol = pair.get('quoteToken', {}).get('symbol', '')
        dex = pair.get('dexId', '')
        
        if not (chain and pair_address and base_symbol and quote_symbol):
            continue
        
        filtered.append({
            'chain': chain,
            'pair_address': pair_address,
            'name': f"{base_symbol}/{quote_symbol}",
            'expected_price': 1.0,  # Для стейблкоинов
            'dex': dex,
            'liquidity_usd': round(liquidity_usd, 2)
        })
    
    return filtered


def main():
    """Основная функция"""
    print("🚀 Начинаю загрузку пар...\n")
    
    # 1. Загружаем список токенов
    tokens = load_targets()
    if not tokens:
        print("❌ Нет токенов для обработки!")
        return
    
    print(f"\n🔍 Обрабатываю {len(tokens)} токенов...\n")
    
    # 2. Ищем пары для каждого токена
    all_pairs = []
    for i, token in enumerate(tokens, 1):
        print(f"[{i}/{len(tokens)}] {token}")
        pairs = search_token_pairs(token)
        all_pairs.extend(pairs)
        
        # Пауза между запросами
        if i < len(tokens):  # Не ждём после последнего
            time.sleep(0.5)
    
    print(f"\n📊 Всего найдено: {len(all_pairs)} пар")
    
    # 3. Фильтруем и форматируем
    filtered_pairs = filter_and_format_pairs(all_pairs)
    print(f"✅ После фильтрации (ликв. > ${MIN_LIQUIDITY:,}): {len(filtered_pairs)} пар")
    
    # 4. Удаляем дубликаты
    unique_pairs = {}
    for pair in filtered_pairs:
        key = f"{pair['chain']}:{pair['pair_address']}"
        if key not in unique_pairs:
            unique_pairs[key] = pair
        else:
            # Если дубликат, берём пару с большей ликвидностью
            if pair['liquidity_usd'] > unique_pairs[key]['liquidity_usd']:
                unique_pairs[key] = pair
    
    final_pairs = list(unique_pairs.values())
    print(f"🎯 Уникальных пар: {len(final_pairs)}")
    
    # 5. Сортируем по ликвидности (самые ликвидные первыми)
    final_pairs.sort(key=lambda x: x['liquidity_usd'], reverse=True)
    
    # 6. Сохраняем в JSON
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_pairs, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Сохранено в {OUTPUT_FILE}")
    
    # 7. Показываем статистику по сетям
    chains_stats = {}
    for pair in final_pairs:
        chain = pair['chain']
        chains_stats[chain] = chains_stats.get(chain, 0) + 1
    
    print("\n📈 Статистика по сетям:")
    for chain, count in sorted(chains_stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {chain}: {count} пар")
    
    # 8. Топ-5 пар по ликвидности
    print("\n🏆 Топ-5 пар по ликвидности:")
    for i, pair in enumerate(final_pairs[:5], 1):
        print(f"  {i}. {pair['name']} ({pair['chain']}/{pair['dex']}) "
              f"- ${pair['liquidity_usd']:,.0f}")
    
    print("\n✨ Готово!")


if __name__ == "__main__":
    main()
