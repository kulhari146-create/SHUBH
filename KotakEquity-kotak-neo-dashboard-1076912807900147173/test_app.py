import unittest
from unittest.mock import MagicMock, patch
import app

class TestKotakDashboard(unittest.TestCase):
    def setUp(self):
        app.app.testing = True
        self.client = app.app.test_client()

    @patch('app.NeoAPI')
    def test_login_step1_success(self, mock_neo):
        mock_instance = mock_neo.return_value
        mock_instance.totp_login.return_value = {"stat": "Ok"}

        response = self.client.post('/api/login/step1', json={
            'mobile_number': '919999999999',
            'ucc': 'TESTUCC',
            'consumer_key': 'TESTKEY',
            'totp': '123456'
        })

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['status'], 'success')
        self.assertIn('session_id', data)

    @patch('app.NeoAPI')
    def test_place_order_params(self, mock_neo):
        # Mock session
        session_id = 'test_session'
        mock_instance = MagicMock()
        mock_instance.place_order.return_value = {"stat": "Ok", "nOrdNo": "123"}
        app.clients[session_id] = {'client': mock_instance}

        order_data = {
            'session_id': session_id,
            'exchange_segment': 'NSECM',
            'product': 'MIS',
            'price': 100.5,
            'order_type': 'L',
            'quantity': 10,
            'trading_symbol': 'SBIN-EQ',
            'transaction_type': 'BUY'
        }

        response = self.client.post('/api/place_order', json=order_data)

        self.assertEqual(response.status_code, 200)
        mock_instance.place_order.assert_called_once_with(
            exchange_segment='nse_cm',
            product='MIS',
            price='100.5',
            order_type='L',
            quantity='10',
            validity='DAY',
            trading_symbol='SBIN-EQ',
            transaction_type='B',
            amo='NO',
            trigger_price='0'
        )

if __name__ == '__main__':
    unittest.main()
