from __future__ import annotations

from datetime import UTC, datetime

import httpx


class RedditClient:
    TOKEN_URL = 'https://www.reddit.com/api/v1/access_token'
    BASE_URL = 'https://oauth.reddit.com'

    def __init__(self, client_id: str | None, client_secret: str | None, user_agent: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent

    async def _get_token(self):
        if not self.client_id or not self.client_secret:
            return None
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={'grant_type': 'client_credentials'},
                headers={'User-Agent': self.user_agent},
                timeout=20,
            )
            response.raise_for_status()
            return response.json()['access_token']

    async def fetch_new_posts(self, subreddit: str, limit: int = 10):
        token = await self._get_token()
        if token is None:
            return []
        headers = {'Authorization': f'Bearer {token}', 'User-Agent': self.user_agent}
        async with httpx.AsyncClient(base_url=self.BASE_URL, headers=headers, timeout=20) as client:
            response = await client.get(f'/r/{subreddit}/new', params={'limit': limit})
            response.raise_for_status()
        payload = response.json()
        results = []
        now = datetime.now(UTC).timestamp()
        for child in payload['data']['children']:
            data = child['data']
            results.append(
                {
                    'reddit_post_id': data['id'],
                    'subreddit': subreddit,
                    'title': data['title'],
                    'body': data.get('selftext', ''),
                    'permalink': f'https://reddit.com{data["permalink"]}',
                    'author': data.get('author'),
                    'freshness_hours': max(0.0, (now - data['created_utc']) / 3600),
                    'num_comments': data.get('num_comments', 0),
                    'source_kind': 'post',
                }
            )
        return results
