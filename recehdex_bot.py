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

# ALAMAT CONTRACT
USD_ADDRESS = "0x6dC1bC519a8c861d509351763a6f9aBb6B07b57B"  # USDr
FACTORY_ADDRESS = "0xAeEdf8B9925c6316171f7c2815e387DE596Fa11B"

RPC_URL = "https://seed-richechain.com"
DEX_URL = "https://dex.cryptoreceh.com"
PAIR_INFO_URL = "https://dex.cryptoreceh.com/info"
CREATE_TOKEN_URL = "https://app.cryptoreceh.com"
BANNER_URL = "https://raw.githubusercontent.com/recehdex/images/refs/heads/main/recehdex-banner.png"

# Koneksi ke Blockchain
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= ABI =================
FACTORY_ABI = [
    {"constant": True, "inputs": [], "name": "allPairsLength", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "uint256"}], "name": "allPairs", "outputs": [{"name": "", "type": "address"}], "type": "function"}
]

PAIR_ABI = [
    {"constant": True, "inputs": [], "name": "getReserves", "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "type": "function"}
]

TOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

# ================= FUNGSI =================
def get_token_info(token_address):
    """Ambil simbol dan decimals token."""
    try:
        token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=TOKEN_ABI)
        symbol = token.functions.symbol().call()
        decimals = token.functions.decimals().call()
        return symbol, decimals
    except Exception as e:
        logger.error(f"Gagal ambil info token {token_address}: {e}")
        return "Unknown", 18

def get_top_3_pairs():
    """Ambil top 3 pair berdasarkan likuiditas USD."""
    try:
        factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI)
        total_pairs = factory.functions.allPairsLength().call()
        logger.info(f"Total pair di factory: {total_pairs}")

        active_pairs = []

        for i in range(total_pairs):
            try:
                pair_address = factory.functions.allPairs(i).call()
                pair_contract = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)

                token0_address = pair_contract.functions.token0().call().lower()
                token1_address = pair_contract.functions.token1().call().lower()
                reserves = pair_contract.functions.getReserves().call()
                reserve0_raw, reserve1_raw = reserves[0], reserves[1]

                # Cek apakah pair ini adalah USDr/TOKEN
                if token0_address == USD_ADDRESS.lower():
                    usd_reserve_raw = reserve0_raw
                    token_reserve_raw = reserve1_raw
                    token_addr = token1_address
                elif token1_address == USD_ADDRESS.lower():
                    usd_reserve_raw = reserve1_raw
                    token_reserve_raw = reserve0_raw
                    token_addr = token0_address
                else:
                    continue

                # Ambil info token
                token_symbol, token_decimals = get_token_info(token_addr)
                
                # Konversi reserve ke angka normal (USDr decimals = 18)
                usd_reserve = usd_reserve_raw / (10 ** 18)
                token_reserve = token_reserve_raw / (10 ** token_decimals)

                # Hitung harga = reserve_token / reserve_usd
                if usd_reserve > 0:
                    price = token_reserve / usd_reserve
                else:
                    price = 0

                # Total likuiditas dalam USD
                liquidity_usd = usd_reserve * 2

                # Filter: likuiditas minimal $1
                if liquidity_usd >= 1 and price > 0:
                    active_pairs.append({
                        "symbol": token_symbol,
                        "address": token_addr,
                        "price": price,
                        "liquidity": liquidity_usd,
                    })
                    logger.info(f"Pair {token_symbol}/USD: price=${price:.8f}, liq=${liquidity_usd:.2f}")

            except Exception as e:
                logger.error(f"Gagal proses pair index {i}: {e}")
                continue

        # Urutkan berdasarkan likuiditas tertinggi
        active_pairs.sort(key=lambda x: x['liquidity'], reverse=True)
        
        # Ambil top 3
        top3 = active_pairs[:3]
        logger.info(f"Top 3 pairs: {[p['symbol'] for p in top3]}")
        
        return top3

    except Exception as e:
        logger.error(f"Error di get_top_3_pairs: {e}")
        return []

async def get_banner():
    """Download banner dari URL"""
    try:
        response = requests.get(BANNER_URL, timeout=10)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        logger.error(f"Gagal download banner: {e}")
    return None

# ================= MAIN =================
async def main():
    logger.info("=" * 50)
    logger.info("🚀 RecehDEX Bot Dimulai...")
    logger.info("=" * 50)
    
    # Cek koneksi
    if not w3.is_connected():
        logger.error("❌ Gagal konek ke Riche Chain")
        return
    
    logger.info(f"✅ Konek ke Riche Chain - Block: {w3.eth.block_number}")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Ambil top 3 pairs
    top_pairs = get_top_3_pairs()
    
    if not top_pairs:
        logger.warning("Tidak ada pair aktif")
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="⚠️ Tidak ada pair aktif di RecehDEX",
            parse_mode=ParseMode.HTML
        )
        return
    
    # ================= BUILD PESAN =================
    message = "🏆 <b>RECEHDEX - TOP 3 PAIRS</b>\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for idx, pair in enumerate(top_pairs, 1):
        # Format harga
        if pair['price'] < 0.0001:
            price_str = f"${pair['price']:.10f}"
        elif pair['price'] < 0.01:
            price_str = f"${pair['price']:.8f}"
        elif pair['price'] < 1:
            price_str = f"${pair['price']:.6f}"
        else:
            price_str = f"${pair['price']:.4f}"
        
        # Format likuiditas
        liq_str = f"${pair['liquidity']:,.2f}"
        
        # Link trade
        trade_url = f"{DEX_URL}?inputCurrency={USD_ADDRESS}&outputCurrency={pair['address']}"
        
        message += f"<b>{idx}. {pair['symbol']}/USD</b>\n"
        message += f"   💰 Price: <code>{price_str}</code>\n"
        message += f"   💧 Liquidity: <code>{liq_str}</code>\n"
        message += f"   🔗 <a href='{trade_url}'>Trade Now</a>\n\n"
    
    message += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC"
    
    # ================= TOMBOL =================
    keyboard = [
        [
            InlineKeyboardButton("📊 RecehDEX", url=DEX_URL),
            InlineKeyboardButton("ℹ️ PairInfo", url=PAIR_INFO_URL),
        ],
        [InlineKeyboardButton("✨ Create Token", url=CREATE_TOKEN_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ================= KIRIM PESAN =================
    banner = await get_banner()
    
    if banner:
        await bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=banner,
            caption=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        logger.info("✅ Pesan + banner berhasil dikirim")
    else:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )
        logger.info("✅ Pesan teks berhasil dikirim")
    
    logger.info("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
