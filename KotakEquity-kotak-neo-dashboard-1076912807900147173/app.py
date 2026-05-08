from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from neo_api_client import NeoAPI
import os
import pyotp
import re
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
CORS(app)

# --- CONFIGURATION (Enter your details here) ---
DEFAULT_MOBILE = ""
DEFAULT_UCC = ""
DEFAULT_CONSUMER_KEY = ""
DEFAULT_MPIN = ""
DEFAULT_TOTP_SECRET = ""
# -----------------------------------------------

clients = {}

def get_client(session_id):
    if session_id == 'mock':
        return 'mock'
    return clients.get(session_id, {}).get('client')

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
    session_id = data.get('session_id')
    if session_id == 'mock':
        return jsonify({'status': 'success'})

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
    session_id = request.args.get('session_id')
    symbol_query = (request.args.get('symbol') or "").upper()

    if session_id == 'mock':
        mock_data = [
            {'pTrdSymbol': 'RELIANCE-EQ', 'pInstrmntName': 'RELIANCE INDUSTRIES', 'pExchSegmt': 'nse_cm', 'pScripCode': '2885'},
            {'pTrdSymbol': 'NIFTY2650821500CE', 'pInstrmntName': 'NIFTY 21500 CE', 'pExchSegmt': 'nse_fo', 'pScripCode': '54321'},
            {'pTrdSymbol': 'NIFTY2650821500PE', 'pInstrmntName': 'NIFTY 21500 PE', 'pExchSegmt': 'nse_fo', 'pScripCode': '54322'},
            {'pTrdSymbol': 'BANKNIFTY2650845000CE', 'pInstrmntName': 'BANKNIFTY 45000 CE', 'pExchSegmt': 'nse_fo', 'pScripCode': '54323'},
            {'pTrdSymbol': 'NIFTY 50', 'pInstrmntName': 'NIFTY 50 INDEX', 'pExchSegmt': 'nse_cm', 'pScripCode': '1'}
        ]
        search_parts = symbol_query.split()
        filtered = [r for r in mock_data if all(part in (str(r.get('pTrdSymbol','')) + " " + str(r.get('pInstrmntName',''))).upper() for part in search_parts)]
        return jsonify({'status': 'success', 'data': filtered})

    client = get_client(session_id)
    if not client:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    try:
        search_parts = symbol_query.split()
        if not search_parts:
            return jsonify({'status': 'success', 'data': []})

        # Try to extract base symbol for API search
        # E.g. "NIFTY 21500 CE" -> "NIFTY"
        # E.g. "NIFTY21500CE" -> "NIFTY"
        alpha_match = re.match(r'^([A-Z]+)', symbol_query)
        base_symbol = alpha_match.group(1) if alpha_match else search_parts[0]

        all_results = []
        segments = ['nse_cm', 'nse_fo', 'bse_cm', 'bse_fo', 'cde_fo', 'mcx_fo']

        for segment in segments:
            try:
                # 1. Try searching with base symbol
                res = client.search_scrip(exchange_segment=segment, symbol=base_symbol)
                data = []
                if isinstance(res, pd.DataFrame):
                    data = res.to_dict('records')
                elif isinstance(res, dict) and 'data' in res:
                    data = res['data']
                elif isinstance(res, list):
                    data = res

                # 2. If nothing found, try with full query (sometimes works for stocks)
                if not data and base_symbol != symbol_query:
                    res2 = client.search_scrip(exchange_segment=segment, symbol=symbol_query)
                    if isinstance(res2, pd.DataFrame):
                        data = res2.to_dict('records')
                    elif isinstance(res2, dict) and 'data' in res2:
                        data = res2['data']
                    elif isinstance(res2, list):
                        data = res2

                # Locally filter for specific strikes/types/expiries
                for item in data:
                    text = (str(item.get('pTrdSymbol', '')) + " " + str(item.get('pInstrmntName', ''))).upper()
                    if all(part in text for part in search_parts):
                        all_results.append(item)
            except:
                continue

        # Deduplicate results by pScripCode
        seen = set()
        unique_results = []
        for r in all_results:
            code = r.get('pScripCode')
            if code not in seen:
                unique_results.append(r)
                seen.add(code)

        return jsonify({'status': 'success', 'data': unique_results[:50]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/quote', methods=['GET'])
def get_quote():
    session_id = request.args.get('session_id')
    if session_id == 'mock':
        return jsonify({'status': 'success', 'data': {'last_traded_price': '2500.00', 'net_change_percentage': '1.5'}})

    token = request.args.get('token')
    exchange = (request.args.get('exchange') or 'nse_cm').lower()
    client = get_client(session_id)
    if not client:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    try:
        exchange = exchange.replace('cm', '_cm').replace('fo', '_fo').replace('__', '_')
        inst_tokens = [{"instrument_token": str(token), "exchange_segment": exchange}]
        response = client.quotes(instrument_tokens=inst_tokens)

        if isinstance(response, pd.DataFrame):
            response = response.to_dict('records')
        elif isinstance(response, dict) and 'data' in response:
            response = response['data']

        if isinstance(response, list) and len(response) > 0:
            response = response[0]

        return jsonify({'status': 'success', 'data': response})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/quotes', methods=['POST'])
def get_quotes():
    data = request.json
    session_id = data.get('session_id')
    if session_id == 'mock':
        return jsonify({'status': 'success', 'data': [
            {'token': '2885', 'last_traded_price': '2500.00', 'net_change_percentage': '1.5'},
            {'token': '54321', 'last_traded_price': '150.00', 'net_change_percentage': '-2.3'},
            {'token': '54322', 'last_traded_price': '145.50', 'net_change_percentage': '1.2'},
            {'token': '54323', 'last_traded_price': '320.00', 'net_change_percentage': '0.5'},
            {'token': '1', 'last_traded_price': '22000.00', 'net_change_percentage': '0.8'}
        ]})

    instruments = data.get('instruments', [])
    client = get_client(session_id)
    if not client:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

    try:
        inst_tokens = []
        for inst in instruments:
            exchange = inst['exchange'].lower().replace('cm', '_cm').replace('fo', '_fo').replace('__', '_')
            inst_tokens.append({"instrument_token": str(inst['token']), "exchange_segment": exchange})

        if not inst_tokens:
            return jsonify({'status': 'success', 'data': []})

        response = client.quotes(instrument_tokens=inst_tokens)
        if isinstance(response, pd.DataFrame):
            response = response.to_dict('records')
        elif isinstance(response, dict) and 'data' in response:
            response = response['data']
        return jsonify({'status': 'success', 'data': response})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/place_order', methods=['POST'])
def place_order():
    data = request.json
    session_id = data.get('session_id')
    if session_id == 'mock':
        return jsonify({'status': 'success', 'data': {'order_id': 'MOCK123'}})

    client = get_client(session_id)
    if not client:
        return jsonify({'status': 'error', 'message': 'Invalid session'}), 401

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
    app.run(debug=False, port=5000)
