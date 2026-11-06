"""Reusable report logic for CLI and a future server-side portal."""
from decimal import Decimal
from datetime import datetime, timezone
from .client import APIError


def usage_rows(get, filters, max_pages=1000):
    params = {'limit': 200, **filters}
    cursors, ids = set(), set()
    for _ in range(max_pages):
        page = get('/api/v1/usage', params)
        if not isinstance(page, dict) or not isinstance(page.get('data'), list) or 'next_cursor' not in page:
            raise ValueError('Invalid usage response; report incomplete')
        for row in page['data']:
            if not isinstance(row, dict) or not row.get('id'):
                raise ValueError('Invalid usage row; report incomplete')
            if row['id'] not in ids:
                ids.add(row['id'])
                yield row
        cursor = page['next_cursor']
        if cursor is None:
            return
        fields = ('cursor_ts', 'cursor_id', 'cursor_after')
        if not isinstance(cursor, dict) or any(k not in cursor for k in fields):
            raise ValueError('Invalid pagination cursor; report incomplete')
        signature = tuple(str(cursor[k]) for k in fields)
        if signature in cursors:
            raise ValueError('Repeated pagination cursor; report incomplete')
        cursors.add(signature)
        params.update({k: cursor[k] for k in fields})
    raise ValueError('Page limit reached; report incomplete. Increase --max-pages')


def summarize(rows):
    models = {}
    token_fields = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens')
    for row in rows:
        model = row.get('model') or '(unknown)'
        item = models.setdefault(model, dict(model=model, requests=0, charged_usd=Decimal(0),
            byok_estimated_usd=Decimal(0), unknown_pricing_requests=0,
            **{f: 0 for f in token_fields}))
        item['requests'] += 1
        for source, target in [('cost_usd', 'charged_usd'), ('estimated_cost_usd', 'byok_estimated_usd')]:
            value = row.get(source)
            if value is None:
                raise ValueError(f'Missing {source}; cannot produce complete money totals')
            amount = Decimal(str(value))
            if not amount.is_finite():
                raise ValueError('Non-finite cost in usage response')
            item[target] += amount
        item['unknown_pricing_requests'] += row.get('pricing_known') is not True
        for field in token_fields:
            item[field] += int(row.get(field) or 0)
    for item in models.values():
        item['total_tokens'] = item['input_tokens'] + item['output_tokens']
    return sorted(models.values(), key=lambda m: (-m['charged_usd'], m['model']))


def report(client, window='7d', model=None, api_key_id=None, max_pages=1000):
    warnings = []
    def optional(path):
        try:
            result = client.get(path)
            return result.get('data', result)
        except APIError as exc:
            if exc.status == 401:
                raise
            warnings.append(str(exc))
            return None
    key = optional('/api/v1/key')
    credits = optional('/api/v1/credits')
    wallet = None
    if credits is not None:
        if not isinstance(credits, dict) or not all(k in credits for k in ('total_credits','total_usage')):
            warnings.append('Unexpected credits schema; balance unavailable')
        else:
            wallet = {k: Decimal(str(credits[k])) for k in ('total_credits','total_usage')}
            wallet['balance_usd'] = wallet['total_credits'] - wallet['total_usage']
    filters = {'window': window, 'model': model, 'api_key_id': api_key_id}
    models = summarize(usage_rows(client.get, filters, max_pages))
    # Only retain documented display metadata, never arbitrary key response fields.
    key_info = {k:key[k] for k in ('usage','limit','limit_remaining') if isinstance(key, dict) and k in key}
    return dict(generated_at=datetime.now(timezone.utc).isoformat(), window=window,
        scope='API-visible usage (normally organization; plan-bound keys are identity scoped)',
        filters={k:v for k,v in filters.items() if v is not None}, wallet=wallet, key=key_info,
        models=models, warnings=warnings,
        quota_note='Wallet and key limits are shared across models. Per-model promotional remaining quota is not exposed by the documented Cost API.',
        settlement_note='Settled usage only; wallet balance does not subtract pending holds. Live pagination is not a frozen snapshot.')
