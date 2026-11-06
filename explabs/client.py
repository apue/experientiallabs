"""Small HTTPS-only, read-only transport. Never expose server error bodies."""
import json
import time
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE_URL = 'https://api.experientiallabs.ai'

class APIError(Exception):
    def __init__(self, path, status=None):
        self.status = status
        hints = {401: 'API key rejected', 403: 'permission denied', 429: 'rate limited'}
        super().__init__(f'{path}: {hints.get(status, "request failed")} (HTTP {status})' if status else f'{path}: network or invalid JSON response')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Client:
    def __init__(self, key, timeout=30):
        self._key = key
        self.timeout = timeout
        self._opener = build_opener(NoRedirect())

    def get(self, path, params=None):
        if not path.startswith('/api/') or '?' in path:
            raise ValueError('Expected an API path')
        query = urlencode({k:v for k,v in (params or {}).items() if v is not None})
        request = Request(BASE_URL + path + ('?' + query if query else ''), headers={
            'Authorization': 'Bearer ' + self._key,
            'Accept': 'application/json', 'User-Agent': 'explabs-cli/0.1'})
        for attempt in range(3):
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    return json.load(response, parse_float=Decimal)
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status in (429, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise APIError(path, status) from None
            except (URLError, TimeoutError, OSError, ValueError):
                raise APIError(path) from None
