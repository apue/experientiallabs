"""Command-line rendering; USD amounts serialize as exact decimal strings."""
import argparse
import json
import sys
from decimal import Decimal
from .client import Client, APIError
from .config import load_key
from .service import report


def money(value):
    return 'unavailable' if value is None else f'${Decimal(str(value)):,.6f}'


def render(result):
    lines = [f'Experiential Labs | {result["window"]} | USD', result['scope'], '']
    wallet = result['wallet']
    lines.append('Wallet balance (settled): ' + money(wallet['balance_usd'] if wallet else None))
    key = result['key']
    limit = 'uncapped' if 'limit' in key and key['limit'] is None else money(key.get('limit'))
    remaining = 'uncapped' if 'limit_remaining' in key and key['limit_remaining'] is None and key.get('limit', 0) is None else money(key.get('limit_remaining'))
    lines += [f'Key daily cap: {limit} | remaining today: {remaining}', '']
    headers = ['MODEL', 'REQUESTS', 'INPUT', 'OUTPUT', 'CHARGED USD', 'BYOK EST USD', 'UNPRICED']
    rows = [[m['model'], str(m['requests']), str(m['input_tokens']), str(m['output_tokens']),
             money(m['charged_usd']), money(m['byok_estimated_usd']), str(m['unknown_pricing_requests'])] for m in result['models']]
    if rows:
        widths = [max(len(str(row[i])) for row in [headers] + rows) for i in range(len(headers))]
        lines += ['  '.join(str(v).ljust(widths[i]) for i,v in enumerate(row)) for row in [headers] + rows]
        lines.append('Total charged: ' + money(sum(m['charged_usd'] for m in result['models'])))
    else:
        lines.append('No settled usage in this window/filter.')
    lines += ['', result['quota_note'], result['settlement_note'], 'Cached input/reasoning are subsets of input/output; BYOK estimates are not provider invoices.']
    lines += ['Warning: ' + warning for warning in result['warnings']]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only Experiential model usage, costs and shared limits.')
    parser.add_argument('--env-file', metavar='PATH', help='Read key only from this dotenv file (never execute it)')
    parser.add_argument('--key-name', default='EXPLABS_API_KEY', help='Dotenv/environment variable name')
    parser.add_argument('--window', choices=['24h','7d','30d'], default='7d')
    parser.add_argument('--model', help='Exact model slug filter')
    parser.add_argument('--api-key-id', help='Filter usage by key UUID; wallet remains organization-wide')
    parser.add_argument('--json', action='store_true', help='Machine-readable report; USD amounts are decimal strings')
    parser.add_argument('--max-pages', type=int, default=1000)
    args = parser.parse_args(argv)
    if args.max_pages < 1:
        parser.error('--max-pages must be positive')
    try:
        key = load_key(args.env_file, args.key_name)
        result = report(Client(key), args.window, args.model, args.api_key_id, args.max_pages)
        output = json.dumps(result, default=str, ensure_ascii=False, indent=2) if args.json else render(result)
        # Defense in depth, including against a response echoing a credential.
        print(output.replace(key, '[REDACTED]'))
        return 2 if result['warnings'] else 0
    except (APIError, OSError, ValueError, TypeError, KeyError) as exc:
        message = str(exc)
        if 'key' in locals():
            message = message.replace(key, '[REDACTED]')
        print('Error: ' + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
