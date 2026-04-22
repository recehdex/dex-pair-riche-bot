import asyncio
from web3 import Web3
from telegram import Bot
from telegram.constants import ParseMode
import logging
from datetime import datetime
import os

# Konfigurasi
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

# Address
USD_ADDRESS = "0x6dC1bC519a8c861d509351763a6f9aBb6B07b57B"
FACTORY_ADDRESS = "0xAeEdf8B9925c6316171f7c2815e387DE596Fa11B"

RPC_URL = "https://seed-richechain.com"
EXPLORER_URL = "https://richescan.com"
DEX_URL = "https://dex.cryptoreceh.com/riche"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ABIs
PAIR_ABI = [
    {"constant": True, "inputs": [], "name": "getReserves", "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
]

TOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

FACTORY_ABI = [
    {"constant": True, "inputs": [], "name": "allPairsLength", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "", "type": "uint256"}], "name": "allPairs", "outputs": [{"name": "", "type": "address"}], "type": "function"}
]

def get_token_info(token_address):
    try:
        token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=TOKEN_ABI)
        return token.functions.symbol().call(), token.functions.decimals().call()
    except:
        return "Unknown", 18

def get_all_pairs():
    try:
        factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY_ADDRESS), abi=FACTORY_ABI)
        total_pairs = factory.functions.allPairsLength().call()
        
        logger.info(f"Total pairs: {total_pairs}")
        
        pairs = []
        for i in range(total_pairs):
            try:
                pair_address = factory.functions.allPairs(i).call()
                pair_contract = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
                
                token0 = pair_contract.functions.token0().call()
                token1 = pair_contract.functions.token1().call()
                reserves = pair_contract.functions.getReserves().call()
                total_supply = pair_contract.functions.totalSupply().call()
                
                token0_symbol, token0_dec = get_token_info(token0)
                token1_symbol, token1_dec = get_token_info(token1)
                
                reserve0 = reserves[0] / (10 ** token0_dec)
                reserve1 = reserves[1] / (10 ** token1_dec)
                lp_supply = total_supply / (10 ** 18)
                
                # Cari token mana yang USD
                usd_reserve = 0
                other_reserve = 0
                other_address = ""
                other_symbol = ""
                
                if token0.lower() == USD_ADDRESS.lower():
                    usd_reserve = reserve0
                    other_reserve = reserve1
                    other_address = token1
                    other_symbol = token1_symbol
                elif token1.lower() == USD_ADDRESS.lower():
                    usd_reserve = reserve1
                    other_reserve = reserve0
                    other_address = token0
                    other_symbol = token0_symbol
                
                # Hitung harga
                price = other_reserve / usd_reserve if usd_reserve > 0 else 0
                
                # Total likuiditas dalam USD
                liquidity_usd = usd_reserve * 2 if usd_reserve > 0 else 0
                
                # Hanya ambil pair yang likuiditasnya > 0
                if liquidity_usd > 0 and price > 0:
                    pairs.append({
                        "address": pair_address,
                        "token0_symbol": token0_symbol,
                        "token1_symbol": token1_symbol,
                        "pair_name": f"{other_symbol}/USD",
                        "price": price,
                        "liquidity_usd": liquidity_usd,
                        "lp_supply": lp_supply,
                        "other_address": other_address,
                        "other_symbol": other_symbol
                    })
            except Exception as e:
                continue
        
        # Urutkan berdasarkan likuiditas
        pairs.sort(key=lambda x: x['liquidity_usd'], reverse=True)
        return pairs
    except Exception as e:
        logger.error(f"Error: {e}")
        return []

def format_caption(pairs, start_idx, end_idx):
    """Format caption dengan link trade langsung"""
    
    caption = "<b>🔥 RECEHDEX - ACTIVE PAIRS</b>\n"
    caption += "<code>═══════════════════════════════</code>\n\n"
    
    for pair in pairs[start_idx:end_idx]:
        # Format harga
        if pair["price"] < 0.000001:
            price_str = f"${pair['price']:.10f}"
        elif pair["price"] < 0.001:
            price_str = f"${pair['price']:.8f}"
        elif pair["price"] < 1:
            price_str = f"${pair['price']:.6f}"
        else:
            price_str = f"${pair['price']:.2f}"
        
        # Link trade (sesuai format yang Anda berikan)
        trade_url = f"{DEX_URL}?inputCurrency={USD_ADDRESS}&outputCurrency={pair['other_address']}"
        
        caption += f"<b>🪙 {pair['pair_name']}</b>\n"
        caption += f"   💰 Price: <code>{price_str}</code>\n"
        caption += f"   💧 Liquidity: <code>${pair['liquidity_usd']:,.0f}</code>\n"
        caption += f"   📦 LP Supply: <code>{pair['lp_supply']:,.0f}</code>\n"
        caption += f"   🔗 <a href='{trade_url}'>Trade on RecehDEX</a>\n\n"
    
    caption += "<code>═══════════════════════════════</code>\n"
    caption += f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>\n"
    
    total = len(pairs)
    current_page = (start_idx // 5) + 1
    total_pages = (total + 4) // 5
    caption += f"\n<i>📄 Page {current_page} of {total_pages} ({total} active pairs)</i>"
    
    return caption

async def main():
    logger.info("Starting RecehDEX Bot...")
    
    if not w3.is_connected():
        logger.error("Cannot connect to Riche Chain")
        return
    
    logger.info(f"Connected to Riche Chain, block: {w3.eth.block_number}")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    pairs = get_all_pairs()
    
    if not pairs:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="⚠️ No active pairs found on RecehDEX",
            parse_mode=ParseMode.HTML
        )
        return
    
    logger.info(f"Found {len(pairs)} active pairs")
    
    # Kirim per 5 pair
    for i in range(0, len(pairs), 5):
        caption = format_caption(pairs, i, i+5)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=caption,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        await asyncio.sleep(1)
    
    logger.info(f"Sent {len(pairs)} pairs in {((len(pairs)+4)//5)} messages")

if __name__ == "__main__":
    asyncio.run(main())
