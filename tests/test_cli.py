import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal
from unittest.mock import patch
from urllib.error import HTTPError
from explabs.client import Client, APIError, NoRedirect
from explabs.cli import main
from explabs.service import report


class FakeClient:
    def get(self, path, params=None):
        if path.endswith('/key'):
            return {'data': {'limit': None, 'limit_remaining': None, 'usage': 2, 'secret': 'not-exported'}}
        if path.endswith('/credits'):
            return {'data': {'total_credits': Decimal('10.1'), 'total_usage': Decimal('0.2')}}
        return {'data': [], 'next_cursor': None}


class IntegrationTests(unittest.TestCase):
    def test_report_balance_and_allowlisted_metadata(self):
        result = report(FakeClient())
        self.assertEqual(result['wallet']['balance_usd'], Decimal('9.9'))
        self.assertNotIn('secret', result['key'])
        self.assertEqual(result['models'], [])

    def test_restricted_wallet_is_unavailable_not_zero(self):
        class Restricted(FakeClient):
            def get(self, path, params=None):
                if path.endswith('/credits'):
                    raise APIError(path, 403)
                return super().get(path, params)
        result = report(Restricted())
        self.assertIsNone(result['wallet'])
        self.assertEqual(len(result['warnings']), 1)

    def test_cli_json_exact_money(self):
        output = io.StringIO()
        with patch('explabs.cli.load_key', return_value='test-secret'), patch('explabs.cli.Client', return_value=FakeClient()), redirect_stdout(output):
            self.assertEqual(main(['--json']), 0)
        self.assertEqual(json.loads(output.getvalue())['wallet']['balance_usd'], '9.9')
        self.assertNotIn('test-secret', output.getvalue())

    def test_cli_secret_redaction_and_no_traceback(self):
        output = io.StringIO()
        with patch('explabs.cli.load_key', return_value='test-secret'), patch('explabs.cli.report', side_effect=ValueError('test-secret')), redirect_stderr(output):
            self.assertEqual(main([]), 1)
        self.assertEqual(output.getvalue(), 'Error: [REDACTED]\n')

    def test_http_error_body_is_never_printed(self):
        client = Client('test-secret')
        error = HTTPError('https://example.invalid', 401, 'test-secret', {}, io.BytesIO(b'test-secret'))
        with patch.object(client._opener, 'open', side_effect=error):
            with self.assertRaises(APIError) as caught:
                client.get('/api/v1/key')
        self.assertNotIn('test-secret', str(caught.exception))

    def test_redirects_do_not_forward_bearer(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_transport_query_and_exact_decimal(self):
        client = Client('test-secret')
        with patch.object(client._opener, 'open', return_value=io.BytesIO(b'{"value": 0.123456789123456789}')) as mock:
            result = client.get('/api/v1/usage', {'model':'a/b', 'window':'7d'})
        self.assertEqual(result['value'], Decimal('0.123456789123456789'))
        self.assertIn('model=a%2Fb', mock.call_args.args[0].full_url)
        self.assertEqual(mock.call_args.args[0].get_method(), 'GET')

    def test_missing_cursor_is_not_silent_success(self):
        class Invalid(FakeClient):
            def get(self, path, params=None):
                return {'data': []} if path.endswith('/usage') else super().get(path, params)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            report(Invalid())
