from flask import Flask, request, jsonify
import uuid
import requests
import hashlib
import hmac
import base64
import time
import json
import os
import random
import string
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

app = Flask(__name__)

# In-memory storage for users
users = {}

#"user_id":"651d4eb8-448f-41d5-aa36-c6de6a2af7aa","wallet_id":"ewallet_9028f13903fc52f595045e87a3ee1178"

# Rapyd API credentials from .env
RAPYD_ACCESS_KEY = os.getenv("RAPYD_ACCESS_KEY")
RAPYD_SECRET_KEY = os.getenv("RAPYD_SECRET_KEY")
RAPYD_BASE_URL = os.getenv("RAPYD_BASE_URL")

def call_rapyd(method, path, body):
    timestamp, signature, salt, body_str = generate_rapyd_signature(method, path, body)
    
    headers = {
        "access_key": RAPYD_ACCESS_KEY,
        "salt": salt,
        "timestamp": timestamp,
        "signature": signature,
        "idempotency": str(uuid.uuid4()),
        "Content-Type": "application/json"
    }
    url = RAPYD_BASE_URL + path
    response = requests.request(method.upper(), url, data=body_str.encode('utf-8'), headers=headers)
    return response

def generate_rapyd_signature(method, path, body):
    """Generates an HMAC signature for Rapyd API requests."""
    timestamp = str(int(time.time()))
    salt = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body else ""
    print('concat', method , path , salt , timestamp , RAPYD_ACCESS_KEY , body_str, RAPYD_SECRET_KEY)
    to_sign = method.lower() + path + salt + timestamp + RAPYD_ACCESS_KEY + RAPYD_SECRET_KEY + body_str
    hash = hmac.new(RAPYD_SECRET_KEY.encode('utf-8'), to_sign.encode('utf-8'), hashlib.sha256)
    signature = base64.urlsafe_b64encode(str.encode(hash.hexdigest()))
    return timestamp, signature, salt, body_str

@app.route("/register", methods=["POST"])
def register():
    """Registers a new trader and creates a Rapyd wallet."""
    data = request.json
    user_id = str(uuid.uuid4())
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    country = data.get("country")
    email = data.get("email")
    phone_number = data.get('phone_number')
    wallet_id = create_wallet(first_name, last_name, country, email, phone_number)
    users[user_id] = {"first_name": data.get("first_name"), "wallet_id": wallet_id}
    return jsonify({"user_id": user_id, "wallet_id": wallet_id, "balance": 0, "message": "User registered successfully."})

def create_wallet(first_name, last_name, country, email, phone_number):
    """Creates a Rapyd eWallet for the trader."""
    wallet_data = {
        "type": "person",
        "first_name": first_name,
        "last_name": last_name,
        "ewallet_reference_id": str(uuid.uuid4()),
        "contact": {
            "phone_number": phone_number,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "country": country,
        }
    }
    
    path = "/v1/ewallets"
    response = call_rapyd('post', path, wallet_data)
    if response.status_code == 200:
        data = response.json()
        print('data======>', data)
        return data['data']['id']
    else:
        print(response.json())
    return None

@app.route("/deposit", methods=["POST"])
def deposit():
    """Handles deposits using Rapyd's Collect API."""
    data = request.json
    amount = data.get("amount")
    currency = data.get("currency", "USD")
    country = data.get("country", "US")
    fund_trader_wallet = data.get("fund_trader_wallet")

    
    # Create a payment checkout page
    # By default the money goes into the trading platform's wallet
    payment_data = {
        "amount": amount,
        "currency": currency,
        "country": country,
        "complete_payment_url": "http://localhost:8000/payment_success",
        "error_payment_url": "http://localhost:8000/payment_failure"
    }
    # this option causes the money to go into the trader's own wallet
    if fund_trader_wallet:
        payment_data.update({
            "ewallet": data.get("wallet_id"),
        })
    
    path = "/v1/checkout"
    response = call_rapyd("post", path, payment_data)

    if response.status_code == 200:
        payment_response = response.json()
        return jsonify({
            "message": "Deposit initiated",
            "checkout_url": payment_response["data"]["redirect_url"]
        })
    else:
        return jsonify(response.json()), response.status_code

@app.route("/payment_success", methods=["GET"])
def payment_success():
    return jsonify({"message": "Payment Succeeded."})

@app.route("/payment_failure", methods=["GET"])
def payment_failure():
    return jsonify({"message": "Payment Failed."})

@app.route("/debit_trader_wallet", methods=["POST"])
def debit_trader_wallet():
    """Debit trader's Rapyd Wallet."""
    data = request.json
    amount = data.get("amount")
    currency = data.get("currency", "USD")

    wallet_id = data.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "User does not have a wallet"}), 400
    
    wallet_data = {
        "ewallet": wallet_id,
        "amount": amount,
        "currency": currency
    }
    
    path = "/v1/account/withdraw"
    response = call_rapyd('post', path, wallet_data)
    
    if response.status_code == 200:
        deposit_response = response.json()
        return jsonify({"message": "Funds removed from wallet", "transaction": deposit_response["data"]})
    else:
        return jsonify(response.json()), response.status_code
    
@app.route("/credit_trader_wallet", methods=["POST"])
def credit_trader_wallet():
    """credit Trader's Rapyd Wallet."""
    data = request.json
    amount = data.get("amount")
    currency = data.get("currency", "USD")

    wallet_id = data.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "User does not have a wallet"}), 400
    
    wallet_data = {
        "ewallet": wallet_id,
        "amount": amount,
        "currency": currency
    }
    
    path = "/v1/account/deposit"
    response = call_rapyd('post', path, wallet_data)
    
    if response.status_code == 200:
        deposit_response = response.json()
        return jsonify({"message": "Funds added to trader's wallet", "transaction": deposit_response["data"]})
    else:
        return jsonify(response.json()), response.status_code
    
@app.route("/get_payout_types", methods=["GET"])
def get_payout_types():
    
    data = request.args
    payout_params = {
        "beneficiary_country": data.get("beneficiary_country"),
        'beneficiary_entity_type': data.get("entity_type"),
        "payout_currency": data.get("payout_currency"),
        "category": data.get("category")
    }

    path = '/v1/payout_method_types?' + '&'.join(list(f'{param}={value}' for param, value in payout_params.items()))

    response = call_rapyd('get', path, None)
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify(response.json()), response.status_code
    
@app.route("/get_payout_required_fields", methods=["GET"])
def get_payout_required_fields():

    data = request.args
    payout_type = data.get('payout_method_type')
    payout_params = {
        "beneficiary_country": data.get("beneficiary_country"),
        'beneficiary_entity_type': data.get("beneficiary_entity_type"),
        "payout_currency": data.get("payout_currency"),
        "payout_amount": data.get("payout_amount"),
        "payout_method_type": data.get("payout_method_type"),
        "sender_currency": data.get("sender_currency"),
        "sender_country": data.get("sender_country"),
        "sender_entity_type": data.get("sender_entity_type")
    }
    params = '&'.join(list(f'{param}={value}' for param, value in payout_params.items()))
    path = f'/v1/payout_methods/{payout_type}/required_fields?{params}'

    response = call_rapyd('get', path, None)
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify(response.json()), response.status_code

@app.route("/payout", methods=["POST"])
def payout():
    """Initiates a payout to a beneficiary."""
    data = request.json
    amount = data.get("amount")
    currency = data.get("currency", "USD")

    wallet_id = data.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "User does not have a wallet"}), 400
    
    payout_data = {
        "beneficiary": data.get("beneficiary"),
        "beneficiary_country": data.get("beneficiary_country"),
        "beneficiary_entity_type": data.get("beneficiary_entity_type"),
        "description": data.get("description"),
        "ewallet": wallet_id,
        "payout_amount": data.get("payout_amount"),
        "payout_currency": data.get("payout_currency"),
        "payout_method_type": data.get("payout_method_type"),
        "sender": data.get("sender"),
        "sender_country": data.get("sender_country"),
        "sender_currency": data.get("sender_currency"),
        "sender_entity_type": data.get("sender_entity_type")
    }
    
    path = "/v1/payouts"
    response = call_rapyd('post', path, payout_data)
    
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify(response.json()), response.status_code
