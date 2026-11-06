"""Live catalog selection, with explicit price units and explainable shortlists."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import re
from .client import APIError

REFERENCE = '1M input + 250k output, without cache, discounts or extra fees'
SPECIALIZED = re.compile(r'(^|[-_/])(image|embed|embedding|transcribe|tts|decisions|uncensored|safeguard|guard)([-_/]|$)')


def price(value):
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid catalog price') from None
    if not amount.is_finite() or amount < 0:
        raise ValueError('Invalid catalog price')
    # /api/v1/models OpenRouter-compatible pricing strings are USD/token.
    # /api/models provider fields use a DIFFERENT unit: nano-USD/million.
    return amount * 1_000_000


def normalize(rows, metadata):
    models = []
    seen = set()
    for row in rows:
        identifier = row['id']
        if identifier in seen:
            continue
        seen.add(identifier)
        slug = row.get('canonical_slug') or identifier.split('/')[-1]
        meta = metadata.get(slug, {})
        pricing = row.get('pricing') or {}
        inp, out = price(pricing.get('prompt')), price(pricing.get('completion'))
        reference = inp + out / 4 if inp is not None and out is not None else None
        band = 'unknown' if reference is None else 'budget' if reference <= 2 else 'balanced' if reference <= 8 else 'premium'
        maker = meta.get('maker') or (identifier.split('/')[0].lstrip('~') if '/' in identifier else 'unknown')
        variant = ':' in identifier or identifier.startswith('~') or 'latest' in slug
        params = row.get('supported_parameters') or []
        output = (row.get('architecture') or {}).get('output_modalities') or []
        if output != ['text']:
            reference, band = None, 'unknown'
        general = output == ['text'] and 'tools' in params and not SPECIALIZED.search(slug)
        models.append(dict(id=identifier, canonical_slug=slug, name=row.get('name') or slug,
            maker=maker, context_tokens=row.get('context_length'),
            max_output_tokens=(row.get('top_provider') or {}).get('max_completion_tokens'),
            input_usd_per_million=inp, output_usd_per_million=out,
            cache_read_usd_per_million=price(pricing.get('input_cache_read')),
            reference_usd=reference, budget_band=band, variant=variant,
            general=general, preferred_rank=meta.get('preferred_rank'),
            capabilities=params, output_modalities=output))
    return models


def select_models(models, *, all_models=False, search=None, maker=None, capability=None,
                  max_cost=None, min_context=0, sort='recommended', limit=None):
    explicit = all_models or search or maker or capability or max_cost is not None or min_context or sort != 'recommended'
    candidates = [m for m in models
        if (not search or search.casefold() in (m['id']+' '+m['name']+' '+m['canonical_slug']).casefold())
        and (not maker or maker.casefold() in m['maker'].casefold())
        and (not capability or capability in m['capabilities'])
        and (not min_context or (m['context_tokens'] or 0) >= min_context)
        and (max_cost is None or m['reference_usd'] is not None and m['reference_usd'] <= max_cost)]
    def rank(m):
        return (m['preferred_rank'] is None, m['preferred_rank'] if m['preferred_rank'] is not None else 0, m['id'])
    if not explicit:
        counts = Counter()
        chosen = []
        for m in sorted(candidates, key=rank):
            if not m['general'] or m['variant'] or m['preferred_rank'] is None or counts[re.sub(r'[^a-z0-9]', '', m['maker'].casefold())] >= 2:
                continue
            chosen.append(m)
            counts[re.sub(r'[^a-z0-9]', '', m['maker'].casefold())] += 1
            if len(chosen) >= (limit or 12):
                break
        candidates = chosen
    if sort == 'price' or not explicit:
        candidates.sort(key=lambda m: (m['reference_usd'] is None, m['reference_usd'] or Decimal(0), rank(m)))
    elif sort == 'context':
        candidates.sort(key=lambda m: (-(m['context_tokens'] or 0), rank(m)))
    elif sort == 'name':
        candidates.sort(key=lambda m: m['id'])
    else:
        candidates.sort(key=rank)
    return candidates[:limit] if limit else candidates


def catalog(client, **options):
    data = client.get('/api/v1/models')
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise ValueError('Invalid models response')
    warnings, metadata = [], {}
    try:
        # Only enrich the leading preferred pool. Complete visible IDs/prices
        # come from /api/v1/models, not this bounded metadata lookup.
        preferred = client.get('/api/models', {'sort':'preferred', 'limit':100})
        if not isinstance(preferred, dict) or not isinstance(preferred.get('models'), list):
            raise ValueError('Invalid preferred catalog response')
        metadata = {r['model']['slug']:r['model'] for r in preferred['models']}
    except APIError as exc:
        if exc.status == 401:
            raise
        warnings.append(str(exc) + '; shortlist unavailable, use --all to view visible models')
    models = normalize(data['data'], metadata)
    selected = select_models(models, **options)
    if not selected:
        warnings.append('No models matched. Use --all or relax filters.')
    return dict(generated_at=datetime.now(timezone.utc).isoformat(), total_visible=len(models),
        shown=len(selected), models=selected, warnings=warnings,
        price_unit='USD per million tokens', reference_workload=REFERENCE,
        selection='Default: platform preferred general text/tool models, at most two per maker, at most 12; ordered by reference cost. Explicit filters/sort search the entire visible catalog.',
        availability='Listed by the API, not inference-tested. Balance, verification, region and routing still apply. :free entries have separate eligibility and allowances.')
