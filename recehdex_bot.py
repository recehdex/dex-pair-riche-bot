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

# Konfigurasi
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

# Contract Addresses
USD_ADDRESS = "0x6dC1bC519a8c861d509351763a6f9aBb6B07b57B"
FACTORY_ADDRESS = "0xAeEdf8B9925c6316171f7c2815e387DE596Fa11B"

# Multiple RPC endpoints (coba satu per satu)
RPC_ENDPOINTS = [
    "https://seed-richechain.com:8586/",
    "https://rpc.richescan.com/",
    "https://richechain-rpc.vercel.app/",
]

EXPLORER_URL = "https://richescan.com"
DEX_URL = "https://dex.cryptoreceh.com/riche"
BANNER_URL = "https://raw.githubusercontent.com/recehdex/images/refs/heads/main/recehdex-banner.png"
CHAIN_ID = 132026

CACHE_FILE = "pairs_cache.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ABIs (sama seperti sebelumnya)
PAIR_ABI = [{"constant": True, "inputs": [], "name": "getReserves", "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}, {"name": "_blockTimestampLast", "type": "uint32"}], "type": "function"}, {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "type": "function"}, {"constant": True, "inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "type": "function"}, {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}]
TOKEN_ABI = [{"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"}, {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}]
FACTORY_ABI = [{"constant": True, "inputs": [], "name": "allPairsLength", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}, {"constant": True, "inputs": [{"name": "", "type": "uint256"}], "name": "allPairs", "outputs": [{"name": "", "type": "address"}], "type": "function"}]

def get_web3_connection():
    """Try multiple RPC endpoints"""
    for rpc in RPC_ENDPOINTS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 10}))
            if w3.is_connected():
                logger.info(f"Connected to Riche Chain via {rpc}")
                return w3, rpc
        except Exception as e:
            logger.warning(f"Failed to connect to {rpc}: {e}")
    return None, None

def get_token_info(w3, token_address: str) -> Tuple[str, int]:
    try:
        token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=TOKEN_ABI)
        symbol = token_contract.functions.symbol().call()
        decimals = token_contract.functions.decimals().call()
        return symbol, decimals
    except:
        return "Unknown", 18

def get_pair_info(w3, pair_address: str) -> Dict:
    try:
        pair_contract = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
        
        token0 = pair_contract.functions.token0().call()
        token1 = pair_contract.functions.token1().call()
        reserves = pair_contract.functions.getReserves().call()
        reserve0 = reserves[0]
        reserve1 = reserves[1]
        total_supply = pair_contract.functions.totalSupply().call()
        
        token0_symbol, token0_decimals = get_token_info(w3, token0)
        token1_symbol, token1_decimals = get_token_info(w3, token1)
        
        usd_reserve = 0
        other_reserve = 0
        other_symbol = ""
        other_address = ""
        
        if token0.lower() == USD_ADDRESS.lower():
            usd_reserve = reserve0 / (10 ** token0_decimals)
            other_reserve = reserve1 / (10 ** token1_decimals)
            other_symbol = token1_symbol
            other_address = token1
        elif token1.lower() == USD_ADDRESS.lower():
            usd_reserve = reserve1 / (10 ** token1_decimals)
            other_reserve = reserve0 / (10 ** token0_decimals)
            other_symbol = token0_symbol
            other_address = token0
        
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
        }
    except Exception as e:
        logger.error(f"Error getting pair info: {e}")
        return None

def get_all_pairs(w3) -> Dict:
    try:
        factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI)
        pairs_count = factory.functions.allPairsLength().call()
        logger.info(f"Total pairs in factory: {pairs_count}")
        
        pairs = {}
        for i in range(min(pairs_count, 200)):
            try:
                pair_address = factory.functions.allPairs(i).call()
                pair_info = get_pair_info(w3, pair_address)
                if pair_info and pair_info['price'] > 0:
                    pairs[pair_address] = pair_info
            except:
                continue
        return pairs
    except Exception as e:
        logger.error(f"Error getting pairs: {e}")
        return {}

async def send_telegram_message(bot: Bot, message: str):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return True
    except Exception as e:
        logger.error(f"Failed to send: {e}")
        return False

async def main():
    logger.info("RecehDEX Bot Started")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Kirim pesan status mencoba konek
    trying_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>🔄 RECEHDEX BOT - CONNECTING</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔗 Target:</b> <code>Riche Chain (ID: {CHAIN_ID})</code>
<b>📡 Status:</b> <code>Trying to connect...</code>

<b>🌐 Trying RPC endpoints:</b>
"""
    for rpc in RPC_ENDPOINTS:
        trying_msg += f"\n<code>  • {rpc}</code>"
    
    trying_msg += "\n\n<code>━━━━━━━━━━━━━━━━━━━━</code>\n<i>⚡ Attempting connection...</i>"
    await send_telegram_message(bot, trying_msg)
    
    # Coba konek
    w3, connected_rpc = get_web3_connection()
    
    if not w3 or not w3.is_connected():
        error_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>❌ CONNECTION FAILED</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔗 Network:</b> <code>Riche Chain</code>
<b>📡 Status:</b> <code>Disconnected</code>

<b>⚠️ All RPC endpoints failed</b>
<b>🔄 Possible issues:</b>
<code>  • RPC endpoint is down</code>
<code>  • Network firewall blocks access</code>
<code>  • Invalid RPC URL</code>

<b>💡 Action required:</b>
<code>  Update RPC_ENDPOINTS in code</code>

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>⚡ Bot will retry on next schedule</i>
"""
        await send_telegram_message(bot, error_msg)
        return
    
    # Sukses konek
    success_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>✅ RECEHDEX BOT ONLINE</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔗 Network:</b> <code>Riche Chain (ID: {CHAIN_ID})</code>
<b>📡 Status:</b> <code>Connected ✅</code>
<b>🌐 RPC:</b> <code>{connected_rpc}</code>
<b>📦 Block:</b> <code>{w3.eth.block_number}</code>

<b>🔍 Scanning for pairs...</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>⚡ Bot is monitoring RecehDEX</i>
"""
    await send_telegram_message(bot, success_msg)
    
    # Cari pairs
    pairs = get_all_pairs(w3)
    
    if not pairs:
        no_pair_msg = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>⚠️ NO PAIRS FOUND</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>🔍 Factory:</b> <code>{FACTORY_ADDRESS}</code>
<b>💵 USD:</b> <code>{USD_ADDRESS}</code>

<b>❌ No active pairs with USD</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>
<i>⚡ Waiting for pairs to be created</i>
"""
        await send_telegram_message(bot, no_pair_msg)
    else:
        summary = f"""
<a href="{BANNER_URL}">&#8205;</a>

<b>📊 PAIRS DETECTED</b>

<code>━━━━━━━━━━━━━━━━━━━━</code>

<b>✅ Active pairs:</b> <code>{len(pairs)}</code>

<b>📈 Top 5 by liquidity:</b>
"""
        sorted_pairs = sorted(pairs.values(), key=lambda x: x['total_liquidity_usd'], reverse=True)[:5]
        for p in sorted_pairs:
            summary += f"\n<code>  • {p['pair_name']}: ${p['total_liquidity_usd']:,.0f}</code>"
        
        summary += "\n\n<code>━━━━━━━━━━━━━━━━━━━━</code>\n<i>⚡ Detailed updates for price changes >5%</i>"
        await send_telegram_message(bot, summary)

if __name__ == "__main__":
    asyncio.run(main())
