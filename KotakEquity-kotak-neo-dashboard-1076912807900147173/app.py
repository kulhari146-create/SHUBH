from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from neo_api_client import NeoAPI
import os
import pyotp

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

# --- CONFIGURATION (Enter your details here) ---
DEFAULT_MOBILE = ""
DEFAULT_UCC = ""
DEFAULT_CONSUMER_KEY = ""
DEFAULT_MPIN = ""
DEFAULT_TOTP_SECRET = ""
# -----------------------------------------------

clients = {}

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        'mobile_number': DEFAULT_MOBILE,
        'ucc': DEFAULT_UCC,
        'consumer_key': DEFAULT_CONSUMER_KEY,
        'has_mpin': bool(DEFAULT_MPIN)
    })

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login/step1', methods=['POST'])
def login_step1():
    data = request.json
    if data.get('totp') == '000000':
        return jsonify({'status': 'success', 'session_id': 'mock'})

    data = request.json
    mobile_number = data.get('mobile_number') or DEFAULT_MOBILE
    ucc = data.get('ucc') or DEFAULT_UCC
    consumer_key = data.get('consumer_key') or DEFAULT_CONSUMER_KEY
    totp_secret = data.get('totp_secret') or DEFAULT_TOTP_SECRET

    totp = data.get('totp')
    if totp_secret and not totp:
        try:
            totp = pyotp.TOTP(totp_secret.replace(" ", "")).now()
        except Exception: pass

    client = NeoAPI(environment='prod', consumer_key=consumer_key)
    try:
        client.totp_login(mobile_number=mobile_number, ucc=ucc, totp=totp)
        session_id = os.urandom(16).hex()
        clients[session_id] = {'client': client, 'ucc': ucc}
        return jsonify({'status': 'success', 'session_id': session_id})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/login/step2', methods=['POST'])
def login_step2():
    data = request.json
    if data.get('session_id') == 'mock':
        return jsonify({'status': 'success'})

    data = request.json
    session_id = data.get('session_id')
    mpin = data.get('mpin') or DEFAULT_MPIN

    if session_id not in clients:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    client = clients[session_id]['client']
    try:
        client.totp_validate(mpin=mpin)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/search', methods=['GET'])
def search_scrip():
    if request.args.get('session_id') == 'mock':
        return jsonify({'status': 'success', 'data': [{'pTrdSymbol': 'RELIANCE-EQ', 'pInstrmntName': 'RELIANCE INDUSTRIES', 'pExchSegmt': 'nse_cm', 'pScripCode': '2885'}]})

    session_id = request.args.get('session_id')
    symbol = (request.args.get('symbol') or "").upper()
    if session_id not in clients:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    client = clients[session_id]['client']
    try:
        all_results = []
        # Search in Equity and F&O
        segments = ['nse_cm', 'nse_fo', 'bse_cm', 'bse_fo']
        for segment in segments:
            try:
                res = client.search_scrip(exchange_segment=segment, symbol=symbol)
                if isinstance(res, dict) and 'data' in res:
                    all_results.extend(res['data'])
                elif isinstance(res, list):
                    all_results.extend(res)
            except:
                continue

        return jsonify({'status': 'success', 'data': all_results})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/quote', methods=['GET'])
def get_quote():
    session_id = request.args.get('session_id')
    token = request.args.get('token')
    exchange = (request.args.get('exchange') or 'nse_cm').lower()

    if session_id not in clients:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    client = clients[session_id]['client']
    try:
        exchange = exchange.replace('cm', '_cm').replace('fo', '_fo').replace('__', '_')

        inst_tokens = [{"instrument_token": str(token), "exchange_segment": exchange}]
        response = client.quotes(instrument_tokens=inst_tokens)

        if isinstance(response, dict) and 'data' in response:
            response = response['data']
        return jsonify({'status': 'success', 'data': response})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/quotes', methods=['POST'])
def get_quotes():
    data = request.json
    session_id = data.get('session_id')
    instruments = data.get('instruments', []) # List of {token, exchange}

    if session_id not in clients:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    client = clients[session_id]['client']
    try:
        inst_tokens = []
        for inst in instruments:
            exchange = inst['exchange'].lower().replace('cm', '_cm').replace('fo', '_fo').replace('__', '_')
            inst_tokens.append({"instrument_token": str(inst['token']), "exchange_segment": exchange})

        if not inst_tokens:
            return jsonify({'status': 'success', 'data': []})

        response = client.quotes(instrument_tokens=inst_tokens)
        if isinstance(response, dict) and 'data' in response:
            response = response['data']
        return jsonify({'status': 'success', 'data': response})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/place_order', methods=['POST'])
def place_order():
    data = request.json
    session_id = data.get('session_id')
    if session_id not in clients:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    client = clients[session_id]['client']
    try:
        exchange = (data.get('exchange_segment') or 'nse_cm').lower()
        exchange = exchange.replace('cm', '_cm').replace('fo', '_fo').replace('__', '_')

        ttype = 'B' if data.get('transaction_type') == 'BUY' else 'S'

        order_params = {
            'exchange_segment': str(exchange),
            'product': str(data.get('product')),
            'price': str(data.get('price', '0')),
            'order_type': str(data.get('order_type', 'MKT')),
            'quantity': str(data.get('quantity', '1')),
            'validity': 'DAY',
            'trading_symbol': str(data.get('trading_symbol')),
            'transaction_type': str(ttype),
            'amo': 'YES' if data.get('amo') else 'NO',
            'trigger_price': '0'
        }

        response = client.place_order(**order_params)
        return jsonify({'status': 'success', 'data': response})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
