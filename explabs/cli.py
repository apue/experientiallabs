"""Command-line rendering; USD amounts serialize as exact decimal strings."""
import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from .client import Client, APIError
from .config import load_key
from .service import report
from .catalog import catalog


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


def render_catalog(result):
    lines = [f'Experiential models | {result["shown"]} shown / {result["total_visible"]} visible',
             'USD / 1M tokens | REF = 1M input + 250k output (no cache/discounts)', '']
    headers = ['BUDGET', 'MODEL ID', 'INPUT', 'OUTPUT', 'CACHE', 'REF USD', 'CONTEXT', 'TOOLS']
    def number(v):
        return '?' if v is None else format(v, '.6f').rstrip('0').rstrip('.') or '0'
    rows = [[m['budget_band'], m['id'], number(m['input_usd_per_million']),
             number(m['output_usd_per_million']), number(m['cache_read_usd_per_million']),
             number(m['reference_usd']), str(m['context_tokens'] or '?'),
             'yes' if 'tools' in m['capabilities'] else '-'] for m in result['models']]
    widths = [max(len(str(row[i])) for row in [headers]+rows) for i in range(len(headers))]
    lines += ['  '.join(str(v).ljust(widths[i]) for i,v in enumerate(row)) for row in [headers]+rows]
    lines += ['', 'Budget bands: <=$2 budget, <=$8 balanced, >$8 premium (reference workload).',
              result['selection'], result['availability']]
    lines += ['Warning: '+w for w in result['warnings']]
    return '\n'.join(lines)


def nonnegative_decimal(value):
    try:
        value = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError('Expected a nonnegative finite amount') from None
    if not value.is_finite() or value < 0:
        raise argparse.ArgumentTypeError('Expected a nonnegative finite amount')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only Experiential model usage, costs and shared limits.')
    parser.add_argument('command', nargs='?', choices=['usage', 'models'], default='usage')
    parser.add_argument('--env-file', metavar='PATH', help='Read key only from this dotenv file (never execute it)')
    parser.add_argument('--key-name', default='EXPLABS_API_KEY', help='Dotenv/environment variable name')
    parser.add_argument('--window', choices=['24h','7d','30d'], default='7d')
    parser.add_argument('--model', help='Exact model slug filter')
    parser.add_argument('--api-key-id', help='Filter usage by key UUID; wallet remains organization-wide')
    parser.add_argument('--json', action='store_true', help='Machine-readable report; USD amounts are decimal strings')
    parser.add_argument('--max-pages', type=int, default=1000)
    group = parser.add_argument_group('models options')
    group.add_argument('--all', action='store_true', help='All visible entries, including aliases/free variants')
    group.add_argument('--search', help='Case-insensitive model ID/name search across the full catalog')
    group.add_argument('--maker', help='Filter model maker (not serving provider)')
    group.add_argument('--capability', choices=['tools','reasoning','structured_outputs'])
    group.add_argument('--max-cost', type=nonnegative_decimal, help='Maximum reference USD: 1M input + 250k output')
    group.add_argument('--min-context', type=int, default=0)
    group.add_argument('--sort', choices=['recommended','price','context','name'], default='recommended')
    group.add_argument('--limit', type=int, help='Limit displayed models; 0 means no display limit (default shortlist still caps at 12)')
    args = parser.parse_args(argv)
    if args.min_context < 0 or args.limit is not None and args.limit < 0:
        parser.error('--min-context and --limit must be nonnegative')
    if args.max_pages < 1:
        parser.error('--max-pages must be positive')
    try:
        key = load_key(args.env_file, args.key_name)
        if args.command == 'models':
            result = catalog(Client(key), all_models=args.all, search=args.search, maker=args.maker,
                             capability=args.capability, max_cost=args.max_cost,
                             min_context=args.min_context, sort=args.sort, limit=args.limit)
            renderer = render_catalog
        else:
            result = report(Client(key), args.window, args.model, args.api_key_id, args.max_pages)
            renderer = render
        output = json.dumps(result, default=str, ensure_ascii=False, indent=2) if args.json else renderer(result)
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
