import os

os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./test_agent.sqlite3'

from fastapi.testclient import TestClient

from services.api.main import app


def test_api_smoke():
    with TestClient(app) as client:
        default_agent = client.get('/agents/default')
        assert default_agent.status_code == 200
        agent_id = default_agent.json()['id']

        health = client.get(f'/agents/{agent_id}/health')
        assert health.status_code == 200

        analytics = client.get('/analytics')
        assert analytics.status_code == 200
        assert 'queued_drafts' in analytics.json()
        assert 'executed_posts' in analytics.json()
