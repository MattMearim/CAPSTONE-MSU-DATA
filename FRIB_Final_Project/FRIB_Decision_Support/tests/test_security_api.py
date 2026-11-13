"""Adversarial local API requests operate only in disposable workspaces."""
import asyncio
import json

import pytest

from test_api_lifecycle import api_environment
from frib_ds.api import security


@pytest.mark.parametrize("origin", ["https://unrelated-site.invalid", "null", "http://localhost.evil.invalid", "http://user@localhost", "http://127.0.0.1/path", "https://127.0.0.1.invalid"])
def test_unrelated_browser_origin_cannot_upload_approved_procedures(api_environment, origin):
    client, _, _ = api_environment
    response = client.post('/documents/index', headers={'Origin': origin},
                           files={'file': ('synthetic.md', b'Fictional procedure for an origin attack.')},
                           data={'approved': 'true'})
    assert response.status_code == 403
    assert client.get('/documents').json() == []


@pytest.mark.parametrize("host", ["attacker.invalid", "localhost.attacker.invalid", "127.0.0.1@attacker.invalid", "localhost/path", "localhost:99999"])
def test_nonlocal_host_is_rejected(api_environment, host):
    client, _, _ = api_environment
    assert client.get('/health', headers={'Host': host}).status_code == 400


@pytest.mark.parametrize("origin", [None, 'http://127.0.0.1:8501', 'http://localhost:8501'])
def test_dashboard_and_cli_requests_remain_supported(api_environment, origin):
    client, _, _ = api_environment
    headers = {} if origin is None else {'Origin': origin}
    response = client.post('/units/convert', headers=headers, json={'value': 2, 'from_unit': 'kPa', 'to_unit': 'Pa'})
    assert response.status_code == 200
    assert response.json()['converted_value'] == 2000
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['cache-control'] == 'no-store'


def test_oversized_body_is_rejected_before_parsing_or_saving(api_environment, monkeypatch):
    client, _, _ = api_environment
    monkeypatch.setattr(security, 'MAX_REQUEST_BYTES', 64)
    assert client.post('/events', content=b'x' * 65, headers={'Content-Type': 'application/json'}).status_code == 413
    assert client.get('/events').json() == []


def test_chunked_request_cannot_bypass_the_total_body_budget(monkeypatch):
    monkeypatch.setattr(security, 'MAX_REQUEST_BYTES', 64)
    messages = iter([
        {'type': 'http.request', 'body': b'a' * 32, 'more_body': True},
        {'type': 'http.request', 'body': b'b' * 33, 'more_body': False},
    ])
    output = []
    reached_route = []
    async def receive(): return next(messages)
    async def send(message): output.append(message)
    async def route(*args): reached_route.append(True)
    middleware = security.LocalRequestSecurityMiddleware(route)
    asyncio.run(middleware({'type': 'http', 'headers': [(b'host', b'127.0.0.1')]}, receive, send))
    assert output[0]['status'] == 413
    assert not reached_route


@pytest.mark.parametrize("text", ['=HYPERLINK("https://invalid.example","click")', '+1+1', '-1+2', '@SUM(1,2)', '  \t=1+1'])
def test_csv_keeps_formula_like_source_text_literal_without_changing_original(api_environment, text):
    import csv
    import io
    client, _, _ = api_environment
    event = {'event_id': 'CSV-SECURITY', 'domain': 'other', 'event_type': 'synthetic',
             'logs': [{'timestamp_s': 0, 'level': 'INFO', 'source': 'synthetic', 'message': text}],
             'provenance': {'source': 'synthetic-security-test'}}
    assert client.post('/events', json=event).status_code == 200
    original = client.get('/events/CSV-SECURITY/download').json()
    assert original['logs'][0]['message'] == text
    exported = client.get('/events/CSV-SECURITY/download?format=csv')
    row = next(csv.DictReader(io.StringIO(exported.text)))
    assert row['message'] == "'" + text
