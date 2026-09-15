"""Minimal pull-worker client; transports JSON and never executes task text."""

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class Client:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Worker endpoint must be http://127.0.0.1:PORT')
        self.url, self.token = url.rstrip('/'), token
        # Explicitly bypass proxy environment for local credentials.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def post(self, path, data=None):
        if not path.startswith('/api/'):
            raise ValueError('Expected an API path')
        request = urllib.request.Request(self.url + path, json.dumps(data or {}).encode(),
                                         {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=8) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            result = json.load(exc)
            raise ValueError(result.get('error', 'Request refused')) from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('Redirect refused; credentials remain on the configured loopback service')
