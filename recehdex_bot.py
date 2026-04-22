import asyncio
import aiohttp
from web3 import Web3
from telegram import Bot
from telegram.constants import ParseMode
import logging
from datetime import datetime
from typing import Dict, Tuple
import os
import json

# Konfigurasi dari environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

# Contract Addresses (lowercase untuk perbandingan)
USD_ADDRESS = "0x6dC1bC519a8c861d509351763a6f9aBb6B07b57B".lower()
WRIC_ADDRESS = "0xEa126036c94Ab6A384A25A70e29E2fE2D4a91e68".lower()
FACTORY_ADDRESS = "0xAeEdf8B9925c6316171f7c2815e387DE596Fa11B"

# Configuration
RPC_URL = "https://seed-richechain.com:8586/"
CHAIN_ID = 132026
EXPLORER_URL = "https://richescan.com"
DEX_URL = "https://dex.cryptoreceh.com/riche"
BANNER_URL = "https://raw.githubusercontent.com/recehdex/images/refs/heads/main/recehdex-banner.png"

# Web3 connection
w3 = Web3(Web3.HTTPProvider(RPC_URL))

CACHE_FILE = "pairs_cache.json"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ABIs
PAIR_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"name": "_reserve0", "type": "uint112"},
            {"name": "_reserve1", "type": "uint112"},
            {"name": "_blockTimestampLast", "type": "uint32"}
        ],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

TOKEN_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]

FACTORY_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "allPairsLength",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "", "type": "uint256"}],
        "name": "allPairs",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function"
    }
]

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def get_token_info(token_address: str) -> Tuple[str, int]:
    try:
        token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=TOKEN_ABI)
        symbol = token_contract.functions.symbol().call()
        decimals = token_contract.functions.decimals().call()
        return symbol, decimals
    except Exception as e:
        logger.error(f"Error getting token info for {token_address}: {e}")
        return "Unknown", 18

def get_pair_info(pair_address: str) -> Dict:
    try:
        pair_contract = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
        
        token0 = pair_contract.functions.token0().call()
        token1 = pair_contract.functions.token1().call()
        reserves = pair_contract.functions.getReserves().call()
        reserve0 = reserves[0]
        reserve1 = reserves[1]
        total_supply = pair_contract.functions.totalSupply().call()
        
        token0_symbol, token0_decimals = get_token_info(token0)
        token1_symbol, token1_decimals = get_token_info(token1)
        
        # Log untuk debug
        logger.info(f"Pair {pair_address}: token0={token0_symbol} ({token0}), token1={token1_symbol} ({token1})")
        
        # Determine which token is USD
        usd_reserve = 0
        other_reserve = 0
        other_symbol = ""
        other_address = ""
        
        if token0.lower() == USD_ADDRESS:
            usd_reserve = reserve0 / (10 ** token0_decimals)
            other_reserve = reserve1 / (10 ** token1_decimals)
            other_symbol = token1_symbol
            other_address = token1
            logger.info(f"Found USD pair: {other_symbol}/USD")
        elif token1.lower() == USD_ADDRESS:
            usd_reserve = reserve1 / (10 ** token1_decimals)
            other_reserve = reserve0 / (10 ** token0_decimals)
            other_symbol = token0_symbol
            other_address = token0
            logger.info(f"Found USD pair: {other_symbol}/USD")
        
        if usd_reserve == 0:
            return None
        
        price = other_reserve / usd_reserve
        total_liquidity_usd = usd_reserve * 2
        
        return {
            "pair_address": pair_address,
            "pair_name": f"{other_symbol}/USD",
            "other_symbol": other_symbol,
            "other_address": other_address,
            "price": price,
            "usd_reserve": usd_reserve,
            "other_reserve": other_reserve,
            "total_liquidity_usd": total_liquidity_usd,
            "total_supply": total_supply / (10 ** 18),
            "last_update": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting pair info for {pair_address}: {e}")
        return None

def get_all_pairs() -> Dict:
    try:
        factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI)
        pairs_count = factory.functions.allPairsLength().call()
        
        logger.info(f"Total pairs in factory: {pairs_count}")
        
        if pairs_count == 0:
            logger.warning("No pairs found in factory! Check if factory address is correct.")
            return {}
        
        pairs = {}
        for i in range(min(pairs_count, 200)):
            try:
                pair_address = factory.functions.allPairs(i).call()
                pair_info = get_pair_info(pair_address)
                
                if pair_info and pair_info['price'] > 0:
                    pairs[pair_address] = pair_info
                    logger.info(f"Active pair: {pair_info['pair_name']} - Price: ${pair_info['price']:.10f} - Liquidity: ${pair_info['total_liquidity_usd']:.2f}")
            except Exception as e:
                logger.error(f"Error processing pair {i}: {e}")
                continue
        
        logger.info(f"Found {len(pairs)} active pairs with USD")
        return pairs
    except Exception as e:
        logger.error(f"Error getting pairs: {e}")
        return {}

def format_telegram_message(pair_info: Dict, is_new: bool = False) -> str:
    status = "🆕 NEW PAIR LISTED" if is_new else "🔄 PAIR UPDATE"
    
    price_str = f"${pair_info['price']:.10f}".rstrip('0').rstrip('.')
    liquidity_str = f"${pair_info['total_liquidity_usd']:,.2f}"
    lp_supply_str = f"{pair_info['total_supply']:,.0f}"
    usd_reserve_str = f"${pair_info['usd_reserve']:,.2f}"
    other_reserve_str = f"{pair_info['other_reserve']:,.2f}"
    
    trade_url = f"{DEX_URL}?inputCurrency={USD_ADDRESS}&outputCurrency={pair_info['other_address']}"
    
    message = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>📢 {status}</b>

<b>🏦 RECEHDEX DEX</b>

<b>🪙 Pair:</b> <code>{pair_info['pair_name']}</code>

<b>💰 Current Price:</b> <code>{price_str}</code>

<b>💧 Total Liquidity:</b> <code>{liquidity_str}</code>

<b>📊 LP Token Supply:</b> <code>{lp_supply_str}</code>

<b>📦 Pool Reserves:</b>
<code>  USD: {usd_reserve_str}</code>
<code>  {pair_info['other_symbol']}: {other_reserve_str}</code>

<b>🔗 Quick Links:</b>
• <a href="{trade_url}">Trade on RecehDEX</a>
• <a href="{EXPLORER_URL}/address/{pair_info['pair_address']}">View on Explorer</a>

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
<i>⚡ Data from Riche Chain</i>
"""
    return message

async def send_telegram_update(bot: Bot, message: str):
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )
        logger.info("Telegram message sent successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to send telegram message: {e}")
        return False

async def main():
    logger.info("=" * 50)
    logger.info("RecehDEX Telegram Bot Started")
    logger.info("=" * 50)
    
    # Check connection
    if not w3.is_connected():
        logger.error("Failed to connect to Riche Chain")
        logger.info("Sending error notification to Telegram...")
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        error_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>❌ CONNECTION ERROR</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔗 Network:</b> <code>Riche Chain</code>
<b>📡 Status:</b> <code>Disconnected</code>
<b>🕐 Time:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</code>

<b>⚠️ Bot cannot connect to Riche Chain</b>
<b>🔄 Please check RPC endpoint</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>⚡ Bot will retry on next schedule</i>
"""
        await send_telegram_update(bot, error_msg)
        return
    
    logger.info(f"Connected to Riche Chain")
    logger.info(f"Current block: {w3.eth.block_number}")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Send startup message
    startup_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>✅ RECEHDEX BOT ONLINE</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔗 Network:</b> <code>Riche Chain (ID: {CHAIN_ID})</code>
<b>📡 Status:</b> <code>Connected</code>
<b>🕐 Started:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</code>
<b>📦 Block:</b> <code>{w3.eth.block_number}</code>

<b>🔍 Scanning for pairs...</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>⚡ Bot is monitoring RecehDEX</i>
"""
    await send_telegram_update(bot, startup_msg)
    
    # Get current pairs
    current_pairs = get_all_pairs()
    
    if not current_pairs:
        logger.warning("No pairs found")
        no_pair_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>⚠️ NO PAIRS FOUND</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔍 Factory:</b> <code>{FACTORY_ADDRESS}</code>
<b>💵 USD Token:</b> <code>{USD_ADDRESS}</code>

<b>❌ No active pairs with USD found</b>

<b>Possible issues:</b>
• Factory address might be incorrect
• No pairs exist on RecehDEX yet
• RPC connection issue

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>⚡ Please verify contract addresses</i>
"""
        await send_telegram_update(bot, no_pair_msg)
        return
    
    # Send first 5 pairs as sample
    sample_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>📊 PAIRS FOUND</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>✅ Total active pairs:</b> <code>{len(current_pairs)}</code>

<b>📈 Top pairs by liquidity:</b>
"""
    sorted_pairs = sorted(current_pairs.values(), key=lambda x: x['total_liquidity_usd'], reverse=True)[:5]
    for pair in sorted_pairs:
        sample_msg += f"\n<code>• {pair['pair_name']}: ${pair['total_liquidity_usd']:,.0f}</code>"
    
    sample_msg += f"\n\n<code>━━━━━━━━━━━━━━━━━━━━</code>\n<i>⚡ Detailed updates will be sent for price changes >5%</i>"
    
    await send_telegram_update(bot, sample_msg)
    
    # Cache current pairs
    save_cache(current_pairs)
    
    logger.info(f"Bot completed - Found {len(current_pairs)} pairs")
    logger.info("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
