import json, os

REPLIED_FILE = 'replied_posts.json'


def _load():
    try:
        if os.path.exists(REPLIED_FILE):
            with open(REPLIED_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
    except:
        pass
    return []


def _save(data):
    with open(REPLIED_FILE, 'w') as f:
        json.dump(data, f)


def already_replied(post_id):
    return post_id in _load()


def mark_replied(post_id):
    data = _load()
    if post_id not in data:
        data.append(post_id)
    _save(data)
