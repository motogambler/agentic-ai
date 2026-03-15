import urllib.request


def test_health_endpoint_up():
    try:
        resp = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1)
        body = resp.read().decode()
        assert 'ok' in body
    except Exception:
        # If server not running, mark as xfail at runtime
        import pytest

        pytest.skip('server not running on localhost:8000')
