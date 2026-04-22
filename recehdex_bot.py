import asyncio
from web3 import Web3
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
import logging
from datetime import datetime
import os
import requests
from decimal import Decimal, getcontext

getcontext().prec = 30

# Konfigurasi
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

# Address (lowercase untuk perbandingan)
USD_ADDRESS = "0x6dC1bC519a8c861d509351763a6f9aBb6B07b57B".lower()
WRIC_ADDRESS = "0xEa126036c94Ab6A384A25A70e29E2fE2D4a91e68".lower()
FACTORY_ADDRESS = "0xAeEdf8B9925c6316171f7c2815e387DE596Fa11B"

RPC_URL = "https://seed-richechain.com"
DEX_URL = "https://dex.cryptoreceh.com/riche"
PAIR_INFO_URL = "https://dex.cryptoreceh.com/info"
CREATE_TOKEN_URL = "https://app.cryptoreceh.com"
BANNER_URL = "https://raw.githubusercontent.com/recehdex/images/refs/heads/main/recehdex-banner.png"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ABIs
PAIR_ABI = [
    {"constant": True, "inputs": [], "name": "getReserves", "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "type": "function"}
]

TOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
]

FACTORY_ABI = [
    {"constant": True, "inputs": [], "name": "allPairsLength", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "uint256"}], "name": "allPairs", "outputs": [{"name": "", "type": "address"}], "type": "function"}
]

def get_token_info(token_address):
    try:
        token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=TOKEN_ABI)
        symbol = token.functions.symbol().call()
        decimals = token.functions.decimals().call()
        return symbol, decimals
    except Exception as e:
        logger.error(f"Token info error {token_address}: {e}")
        return "Unknown", 18

def get_top_pairs():
    """Ambil top 3 pair berdasarkan likuiditas USD - HITUNG MANUAL"""
    try:
        factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI)
        total_pairs = factory.functions.allPairsLength().call()
        
        logger.info(f"Total pairs di factory: {total_pairs}")
        
        valid_pairs = []
        
        for i in range(total_pairs):
            try:
                pair_address = factory.functions.allPairs(i).call()
                pair_contract = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
                
                token0 = pair_contract.functions.token0().call().lower()
                token1 = pair_contract.functions.token1().call().lower()
                reserves = pair_contract.functions.getReserves().call()
                reserve0_raw = reserves[0]
                reserve1_raw = reserves[1]
                
                # Dapatkan info token
                token0_symbol, token0_dec = get_token_info(token0)
                token1_symbol, token1_dec = get_token_info(token1)
                
                # Konversi reserve ke decimal
                reserve0 = reserve0_raw / (10 ** token0_dec)
                reserve1 = reserve1_raw / (10 ** token1_dec)
                
                # Cari mana yang USD
                if token0 == USD_ADDRESS:
                    # Pair: USD / TOKEN
                    usd_reserve = reserve0
                    token_reserve = reserve1
                    token_symbol = token1_symbol
                    token_address = token1
                    token_decimals = token1_dec
                    price = token_reserve / usd_reserve if usd_reserve > 0 else 0
                    
                elif token1 == USD_ADDRESS:
                    # Pair: TOKEN / USD
                    usd_reserve = reserve1
                    token_reserve = reserve0
                    token_symbol = token0_symbol
                    token_address = token0
                    token_decimals = token0_dec
                    price = token_reserve / usd_reserve if usd_reserve > 0 else 0
                else:
                    # Bukan pair USD, skip
                    continue
                
                # Hitung total likuiditas dalam USD
                liquidity_usd = usd_reserve * 2
                
                # Filter: harga harus masuk akal dan likuiditas > 0
                if price > 0 and price < 1000000 and liquidity_usd > 0:
                    valid_pairs.append({
                        "symbol": token_symbol,
                        "address": token_address,
                        "price": price,
                        "liquidity": liquidity_usd,
                        "pair_address": pair_address,
                        "usd_reserve": usd_reserve,
                        "token_reserve": token_reserve
                    })
                    logger.info(f"Pair {token_symbol}/USD: price={price:.10f}, liq={liquidity_usd:.2f}")
                    
            except Exception as e:
                logger.error(f"Error processing pair {i}: {e}")
                continue
        
        # Urutkan berdasarkan likuiditas tertinggi
        valid_pairs.sort(key=lambda x: x['liquidity'], reverse=True)
        
        # Ambil top 3
        top_pairs = valid_pairs[:3]
        logger.info(f"Found {len(valid_pairs)} valid pairs, top 3: {[p['symbol'] for p in top_pairs]}")
        
        return top_pairs
        
    except Exception as e:
        logger.error(f"Error in get_top_pairs: {e}")
        return []

async def get_banner():
    """Download banner"""
    try:
        response = requests.get(BANNER_URL, timeout=10)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        logger.error(f"Banner download error: {e}")
    return None

async def main():
    logger.info("=" * 50)
    logger.info("RecehDEX Bot Starting...")
    logger.info("=" * 50)
    
    # Cek koneksi
    if not w3.is_connected():
        logger.error("Cannot connect to Riche Chain")
        error_msg = "⚠️ Cannot connect to Riche Chain. Please check RPC endpoint."
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=error_msg)
        return
    
    logger.info(f"Connected to Riche Chain - Block: {w3.eth.block_number}")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Ambil top 3 pairs
    top_pairs = get_top_pairs()
    
    if not top_pairs:
        logger.warning("No valid pairs found")
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="⚠️ No valid pairs found on RecehDEX",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Build message
    message = "<b>🏆 RECEHDEX - TOP 3 PAIRS</b>\n"
    message += "<code>━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n\n"
    
    for idx, pair in enumerate(top_pairs, 1):
        # Format price dengan benar
        if pair['price'] < 0.000001:
            price_str = f"${pair['price']:.12f}"
        elif pair['price'] < 0.0001:
            price_str = f"${pair['price']:.10f}"
        elif pair['price'] < 0.01:
            price_str = f"${pair['price']:.8f}"
        elif pair['price'] < 1:
            price_str = f"${pair['price']:.6f}"
        else:
            price_str = f"${pair['price']:.4f}"
        
        # Format liquidity
        if pair['liquidity'] < 1:
            liq_str = f"${pair['liquidity']:.2f}"
        elif pair['liquidity'] < 1000:
            liq_str = f"${pair['liquidity']:.2f}"
        else:
            liq_str = f"${pair['liquidity']:,.0f}"
        
        # Trade URL
        trade_url = f"{DEX_URL}?inputCurrency={USD_ADDRESS}&outputCurrency={pair['address']}"
        
        message += f"<b>{idx}. {pair['symbol']}/USD</b>\n"
        message += f"   💰 Price: <code>{price_str}</code>\n"
        message += f"   💧 Liquidity: <code>{liq_str}</code>\n"
        message += f"   🔗 <a href='{trade_url}'>Trade Now</a>\n\n"
    
    message += "<code>━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
    message += f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
    
    # Tombol inline
    keyboard = [
        [
            InlineKeyboardButton("📊 RecehDEX", url=DEX_URL),
            InlineKeyboardButton("ℹ️ PairInfo", url=PAIR_INFO_URL),
        ],
        [
            InlineKeyboardButton("✨ Create Token", url=CREATE_TOKEN_URL),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Download dan kirim banner
    banner = await get_banner()
    
    if banner:
        await bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=banner,
            caption=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        logger.info("✅ Sent banner + top 3 pairs")
    else:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )
        logger.info("✅ Sent top 3 pairs (no banner)")
    
    logger.info("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
