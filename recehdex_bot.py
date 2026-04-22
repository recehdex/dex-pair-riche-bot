import asyncio
from web3 import Web3
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
import logging
from datetime import datetime
import os
import requests

# ================= KONFIGURASI =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

# ================= ADDRESS =================
FACTORY_ADDRESS = "0xAeEdf8B9925c6316171f7c2815e387DE596Fa11B"
ROUTER_ADDRESS = "0x8E9556415124b6C726D5C3610d25c24Be8AC2304"
USD_ADDRESS = "0x6dC1bC519a8c861d509351763a6f9aBb6B07b57B"  # USDr
WRIC_ADDRESS = "0xEa126036c94Ab6A384A25A70e29E2fE2D4a91e68"

RPC_URL = "https://seed-richechain.com"
DEX_URL = "https://dex.cryptoreceh.com"
PAIR_INFO_URL = "https://dex.cryptoreceh.com/info"
CREATE_TOKEN_URL = "https://app.cryptoreceh.com"
BANNER_URL = "https://raw.githubusercontent.com/recehdex/images/refs/heads/main/recehdex-banner.png"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= ABI =================
FACTORY_ABI = [
    {"inputs": [], "name": "allPairsLength", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "name": "allPairs", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "address", "name": "tokenA", "type": "address"}, {"internalType": "address", "name": "tokenB", "type": "address"}], "name": "getPair", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"}
]

PAIR_ABI = [
    {"inputs": [], "name": "getReserves", "outputs": [{"internalType": "uint112", "name": "_reserve0", "type": "uint112"}, {"internalType": "uint112", "name": "_reserve1", "type": "uint112"}, {"internalType": "uint32", "name": "_blockTimestampLast", "type": "uint32"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"}
]

TOKEN_ABI = [
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"}
]

ROUTER_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"}, {"internalType": "address", "name": "tokenIn", "type": "address"}, {"internalType": "address", "name": "tokenOut", "type": "address"}], "name": "getAmountOut", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
]

# ================= FUNGSI =================
def get_token_info(token_address):
    try:
        token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=TOKEN_ABI)
        symbol = token.functions.symbol().call()
        decimals = token.functions.decimals().call()
        return symbol, decimals
    except:
        return "Unknown", 18

def get_price_via_router(token_address):
    """Dapatkan harga token dalam USD via Router (1 token = berapa USD)"""
    try:
        router = w3.eth.contract(address=Web3.to_checksum_address(ROUTER_ADDRESS), abi=ROUTER_ABI)
        amount_in = 10 ** 18  # 1 token (dengan 18 decimals)
        
        # Coba dapatkan amount out dalam USD
        amount_out_raw = router.functions.getAmountOut(amount_in, token_address, USD_ADDRESS).call()
        
        # Dapatkan decimals USD (harusnya 18)
        usd_symbol, usd_dec = get_token_info(USD_ADDRESS)
        
        price = amount_out_raw / (10 ** usd_dec)
        return price
    except Exception as e:
        logger.error(f"Router error for {token_address}: {e}")
        return 0

def get_top_3_pairs():
    """Ambil semua pair dari factory, hitung harga via router, urutkan berdasarkan likuiditas USD"""
    try:
        factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI)
        total_pairs = factory.functions.allPairsLength().call()
        logger.info(f"Total pairs: {total_pairs}")
        
        pairs_data = []
        
        for i in range(total_pairs):
            try:
                pair_address = factory.functions.allPairs(i).call()
                pair = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
                
                token0 = pair.functions.token0().call()
                token1 = pair.functions.token1().call()
                reserves = pair.functions.getReserves().call()
                
                token0_symbol, token0_dec = get_token_info(token0)
                token1_symbol, token1_dec = get_token_info(token1)
                
                reserve0 = reserves[0] / (10 ** token0_dec)
                reserve1 = reserves[1] / (10 ** token1_dec)
                
                # Cari harga dalam USD untuk token0 dan token1
                price0 = get_price_via_router(token0)
                price1 = get_price_via_router(token1)
                
                # Hitung total likuiditas dalam USD
                liquidity_usd = 0
                if price0 > 0:
                    liquidity_usd += reserve0 * price0
                if price1 > 0:
                    liquidity_usd += reserve1 * price1
                
                # Hitung harga pair (jika salah satu adalah USD)
                pair_price = 0
                pair_symbol = ""
                pair_token_address = ""
                
                if token0.lower() == USD_ADDRESS.lower():
                    pair_price = price1 if price1 > 0 else reserve1 / reserve0
                    pair_symbol = token1_symbol
                    pair_token_address = token1
                elif token1.lower() == USD_ADDRESS.lower():
                    pair_price = price0 if price0 > 0 else reserve0 / reserve1
                    pair_symbol = token0_symbol
                    pair_token_address = token0
                
                if liquidity_usd > 0 and pair_price > 0:
                    pairs_data.append({
                        "symbol": pair_symbol,
                        "address": pair_token_address,
                        "price": pair_price,
                        "liquidity": liquidity_usd,
                        "pair_name": f"{pair_symbol}/USD"
                    })
                    logger.info(f"{pair_symbol}/USD: price=${pair_price:.8f}, liq=${liquidity_usd:.2f}")
                    
            except Exception as e:
                logger.error(f"Error pair {i}: {e}")
                continue
        
        pairs_data.sort(key=lambda x: x['liquidity'], reverse=True)
        return pairs_data[:3]
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return []

async def get_banner():
    try:
        response = requests.get(BANNER_URL, timeout=10)
        if response.status_code == 200:
            return response.content
    except:
        pass
    return None

async def main():
    logger.info("=" * 50)
    logger.info("RecehDEX Bot - Data Real dari Factory & Router")
    logger.info("=" * 50)
    
    if not w3.is_connected():
        logger.error("Cannot connect to Riche Chain")
        return
    
    logger.info(f"Connected - Block: {w3.eth.block_number}")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    top_pairs = get_top_3_pairs()
    
    if not top_pairs:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="⚠️ No pairs found")
        return
    
    # Build message
    message = "🏆 <b>RECEHDEX - TOP 3 PAIRS</b>\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for idx, pair in enumerate(top_pairs, 1):
        # Format price
        if pair['price'] < 0.0001:
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
        else:
            liq_str = f"${pair['liquidity']:,.2f}"
        
        # Link trade
        trade_url = f"{DEX_URL}?inputCurrency={USD_ADDRESS}&outputCurrency={pair['address']}"
        
        message += f"<b>{idx}. {pair['pair_name']}</b>\n"
        message += f"   💰 Price: <code>{price_str}</code>\n"
        message += f"   💧 Liquidity: <code>{liq_str}</code>\n"
        message += f"   🔗 <a href='{trade_url}'>Trade Now</a>\n\n"
    
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    message += "📊 Data real dari Factory + Router RecehDEX"
    
    # Tombol
    keyboard = [
        [InlineKeyboardButton("📊 RecehDEX", url=DEX_URL)],
        [InlineKeyboardButton("ℹ️ PairInfo", url=PAIR_INFO_URL)],
        [InlineKeyboardButton("✨ Create Token", url=CREATE_TOKEN_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Kirim
    banner = await get_banner()
    if banner:
        await bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=banner,
            caption=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    
    logger.info("Done")

if __name__ == "__main__":
    asyncio.run(main())
