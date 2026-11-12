"""Synthetic local pricing and budget fixture; never a production default."""
import json
import ssl
from contextlib import contextmanager
from unittest.mock import patch
PRICE={'version':'synthetic-v1','model':'deepseek-flash','currency':'USD','input_cache_hit_per_million':'0.02','input_cache_miss_per_million':'0.5','output_per_million':'2'}
ENV={'DEEPSEEK_PRICING_JSON':json.dumps(PRICE),'DEEPSEEK_MODEL':'deepseek-flash'}


@contextmanager
def prepared_https_context():
    """Keep OS certificate-store preparation outside short blocking fixtures.

    The gateway still starts its real deadline before building the opener.
    Only the already prepared context is supplied at the stdlib TLS boundary.
    Expiry during preparation is covered separately in test_ai_deadline.
    """
    context = ssl._create_default_https_context()
    with patch('ssl._create_default_https_context', return_value=context):
        yield
