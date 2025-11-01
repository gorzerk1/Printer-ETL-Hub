# adapters/http_legacy.py
from __future__ import annotations
import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from typing import Optional


class TLSLegacyAdapter(HTTPAdapter):
    def __init__(self, min_version=None, max_version=None, **kwargs):
        self._min_version = min_version
        self._max_version = max_version
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        if hasattr(ctx, "minimum_version") and hasattr(ssl, "TLSVersion"):
            ctx.minimum_version = self._min_version or ssl.TLSVersion.TLSv1
            ctx.maximum_version = self._max_version or ssl.TLSVersion.TLSv1_2
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
            **pool_kwargs,
        )


def make_legacy_session(timeout: float = 4.0) -> requests.Session:
    s = requests.Session()
    s.mount("https://", TLSLegacyAdapter())
    s.mount("http://", TLSLegacyAdapter())
    s.timeout = timeout
    return s
