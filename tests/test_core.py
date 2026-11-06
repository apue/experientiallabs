import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from explabs.config import load_key
from explabs.service import summarize, usage_rows

class CoreTests(unittest.TestCase):
    def test_dotenv_is_data_and_explicit_file_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / '.env'
            p.write_text('export EXPLABS_API_KEY="xpl_local" # comment\nOTHER=$(touch /tmp/never-execute)\n')
            self.assertEqual(load_key(p, 'EXPLABS_API_KEY'), 'xpl_local')

    def test_money_tokens_unknown_and_failed_calls(self):
        rows = [dict(id='1', model='m', cost_usd=Decimal('0.1'), estimated_cost_usd=0,
                     input_tokens=10, cached_input_tokens=4, output_tokens=6, reasoning_tokens=2,
                     pricing_known=True, status='failed'),
                dict(id='2', model='m', cost_usd=Decimal('0.2'), estimated_cost_usd=0,
                     input_tokens=0, output_tokens=0, pricing_known=False)]
        m = summarize(rows)[0]
        self.assertEqual(m['charged_usd'], Decimal('0.3'))
        self.assertEqual(m['total_tokens'], 16)
        self.assertEqual(m['unknown_pricing_requests'], 1)
        self.assertEqual(m['requests'], 2)

    def test_pagination_filters_and_dedup(self):
        calls = []
        def get(path, params):
            calls.append(dict(params))
            if len(calls) == 1:
                return {'data': [{'id':'1'}], 'next_cursor': {'cursor_ts':'ts','cursor_id':'1','cursor_after':'a'}}
            return {'data': [{'id':'1'}, {'id':'2'}], 'next_cursor': None}
        self.assertEqual(list(usage_rows(get, {'window':'30d','model':'m'}, 10)), [{'id':'1'}, {'id':'2'}])
        self.assertEqual(calls[1]['cursor_after'], 'a')
        self.assertEqual(calls[1]['model'], 'm')

    def test_repeated_cursor_and_page_cap_fail_closed(self):
        def get(path, params):
            return {'data':[], 'next_cursor': {'cursor_ts':'t','cursor_id':'i','cursor_after':'a'}}
        for cap in (1, 5):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                list(usage_rows(get, {}, cap))

if __name__ == '__main__':
    unittest.main()
