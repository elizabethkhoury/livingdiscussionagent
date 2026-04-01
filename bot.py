import time, os, asyncio, json, random, re
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from semantic_filter import is_relevant
from reply_generator import generate_reply
from quality_scorer import score_reply
from thread_monitor import already_replied, mark_replied

load_dotenv()

USERNAME = os.getenv('REDDIT_USERNAME')
PASSWORD = os.getenv('REDDIT_PASSWORD')

PROFILE_DIR = os.path.join(os.path.dirname(__file__), 'chrome_profile')

# Only subreddits where prompt/AI-output quality is genuinely discussed
SUBREDDITS = [
    'PromptEngineering', 'ChatGPTPromptEngineering', 'aipromptprogramming',
    'promptdesign', 'ClaudeAI', 'ChatGPT', 'OpenAI', 'midjourney',
    'StableDiffusion', 'AIAssistants', 'cursor', 'lovable', 'CursorAI',
    'vibecoding', 'VibeCodingSaaS', 'vibecodersnest', 'vibecodedevs',
    'nocode', 'nocodesaas', 'boltnewbuilders', 'base44', 'replit', 'Lovable',
    'learnmachinelearning', 'learnprogramming', 'SideProject', 'sideprojects',
    'microsaas', 'indiehackers', 'buildinpublic', 'solopreneur',
]

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)


async def make_context(p):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    context = await p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--start-maximized',
        ],
        user_agent=USER_AGENT,
        viewport={'width': 1280, 'height': 900},
        locale='en-US',
        timezone_id='America/New_York',
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
        window.chrome = { runtime: {} };
    """)
    page = await context.new_page()
    return context, page


async def is_logged_in(page):
    try:
        content = await page.content()
        return USERNAME.lower() in content.lower()
    except:
        return False


async def login(page):
    await page.goto('https://www.reddit.com/', wait_until='domcontentloaded')
    await page.wait_for_timeout(3000)
    if await is_logged_in(page):
        print('Already logged in!')
        return
    print('Logging in...')
    await page.goto('https://www.reddit.com/login', wait_until='domcontentloaded')
    await page.wait_for_timeout(4000)
    await page.fill('input[name="username"]', USERNAME)
    await page.wait_for_timeout(700)
    await page.fill('input[name="password"]', PASSWORD)
    await page.wait_for_timeout(700)
    await page.keyboard.press('Enter')
    await page.wait_for_timeout(6000)
    if await is_logged_in(page):
        print('Logged in!')
    else:
        print('WARNING: login may have failed - check the browser')


async def check_rate_limit(page):
    """
    Detect Reddit rate limit messages anywhere on the page (body text, banners, alerts).
    Waits the full demanded time plus a 30s buffer, then returns True.
    Also handles generic 'server error / try again' responses.
    """
    try:
        text = await page.inner_text('body')
        lower = text.lower()

        triggered = (
            'rate limit' in lower
            or 'ratelimit' in lower
            or ('try again' in lower and ('error' in lower or 'wait' in lower))
        )

        if triggered:
            # Try to find the exact number of seconds Reddit wants us to wait
            match = re.search(r'wait\s+(\d+)\s+second', lower)
            wait_seconds = int(match.group(1)) if match else 120
            total = wait_seconds + 30        # always overshoot by 30s
            print(f'Rate limit detected — waiting {total}s (reddit asked for {wait_seconds}s)...')
            await asyncio.sleep(total)
            return True
    except:
        pass
    return False


async def get_new_posts(page, subreddit):
    posts = []
    try:
        await page.goto(
            f'https://www.reddit.com/r/{subreddit}/new.json?limit=25',
            wait_until='domcontentloaded'
        )
        await page.wait_for_timeout(2000)
        content = await page.inner_text('pre')
        data = json.loads(content)
        for post in data['data']['children']:
            p = post['data']
            posts.append({
                'id': p['id'],
                'title': p['title'],
                'body': p.get('selftext', ''),
                'url': f"https://www.reddit.com{p['permalink']}",
                'age_hours': (time.time() - p['created_utc']) / 3600,
                'subreddit': subreddit,
                'num_comments': p.get('num_comments', 0),
            })
    except Exception as e:
        print(f'Error fetching r/{subreddit}: {str(e)[:50]}')
    return posts


async def get_comments(page, post_url):
    comments = []
    try:
        base = post_url.rstrip('/')
        await page.goto(base + '.json?limit=10', wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)
        content = await page.inner_text('pre')
        data = json.loads(content)
        for c in data[1]['data']['children']:
            if c['kind'] == 't1':
                body = c['data'].get('body', '')
                author = c['data'].get('author', '')
                if body and author != 'AutoModerator' and author != USERNAME and len(body) > 20:
                    comments.append({
                        'id': c['data'].get('id', ''),
                        'body': body,
                        'author': author,
                    })
    except Exception as e:
        print(f'Error getting comments: {str(e)[:60]}')
    return comments


# ---------------------------------------------------------------------------
# Core posting helpers — rebuilt for reliability
# ---------------------------------------------------------------------------

async def _wait_for_editor(page, timeout_ms=8000):
    """
    Wait until at least one visible contenteditable exists and return its coords.
    Tries both shadow-DOM piercing and standard DOM queries.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        coords = await page.evaluate('''() => {
            // Reddit new UI keeps the editor inside a shadow root sometimes
            function findEditors(root) {
                let results = [];
                const els = root.querySelectorAll('[contenteditable="true"]');
                for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 80 && r.height > 10 && r.top >= 0 && r.top < 900) {
                        results.push({ x: r.left + r.width / 2, y: r.top + r.height / 2, h: r.height, top: r.top });
                    }
                }
                // Walk shadow roots one level deep
                const hosts = root.querySelectorAll('*');
                for (const host of hosts) {
                    if (host.shadowRoot) {
                        const inner = host.shadowRoot.querySelectorAll('[contenteditable="true"]');
                        for (const el of inner) {
                            const r = el.getBoundingClientRect();
                            if (r.width > 80 && r.height > 10 && r.top >= 0 && r.top < 900) {
                                results.push({ x: r.left + r.width / 2, y: r.top + r.height / 2, h: r.height, top: r.top });
                            }
                        }
                    }
                }
                return results;
            }
            return findEditors(document);
        }''')
        if coords:
            # pick the lowest one on screen (most likely to be the active composer)
            best = sorted(coords, key=lambda c: c['top'])[-1]
            return best
        await page.wait_for_timeout(300)
    return None


async def _open_post_composer(page):
    """
    Open the top-level comment composer on a post page.
    Strategy: click the 'Join the conversation' placeholder, then wait for an editor.
    Falls back to clicking the shreddit-comment-composer element.
    """
    await page.evaluate('window.scrollTo(0, 0)')
    await page.wait_for_timeout(1500)

    # Strategy 1 — click the visible placeholder text
    for scroll_y in range(0, 4000, 200):
        await page.evaluate(f'window.scrollTo(0, {scroll_y})')
        await page.wait_for_timeout(80)

        clicked = await page.evaluate('''() => {
            // "Join the conversation" placeholder div (new shreddit UI)
            const placeholders = Array.from(document.querySelectorAll(
                'div[data-placeholder], [placeholder], textarea, ' +
                'shreddit-comment-composer, [data-testid="comment-composer"]'
            ));
            for (const el of placeholders) {
                const r = el.getBoundingClientRect();
                if (r.width > 100 && r.height > 0 && r.top > 50 && r.top < 750) {
                    el.click();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
            }
            // Also look for the collapsed "Join the conversation" bar
            const all = Array.from(document.querySelectorAll('*'));
            for (const el of all) {
                const txt = el.innerText || '';
                if (txt.trim() === 'Join the conversation' || txt.trim() === 'What are your thoughts?') {
                    const r = el.getBoundingClientRect();
                    if (r.width > 100 && r.top > 50 && r.top < 750) {
                        el.click();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                }
            }
            return null;
        }''')

        if clicked:
            print(f'Clicked composer placeholder at scroll={scroll_y}')
            await page.wait_for_timeout(1200)
            editor = await _wait_for_editor(page)
            if editor:
                return editor
            # Try one mouse click on the coords reported
            await page.mouse.click(clicked['x'], clicked['y'])
            await page.wait_for_timeout(1200)
            editor = await _wait_for_editor(page)
            if editor:
                return editor

    # Strategy 2 — use Playwright locator for the textarea / contenteditable
    print('Trying locator-based fallback for post composer...')
    for selector in [
        'shreddit-comment-composer [contenteditable]',
        '[data-testid="comment-composer"] [contenteditable]',
        'textarea[placeholder*="comment"]',
        '[contenteditable="true"]',
    ]:
        try:
            loc = page.locator(selector).first
            await loc.scroll_into_view_if_needed(timeout=3000)
            await loc.click(timeout=3000)
            await page.wait_for_timeout(800)
            editor = await _wait_for_editor(page)
            if editor:
                print(f'Opened composer via selector: {selector}')
                return editor
        except Exception:
            pass

    print('Could not open post-level comment composer')
    return None


async def _open_reply_composer(page):
    """
    Click the Reply button under the first visible comment.
    """
    for scroll_y in range(300, 8000, 250):
        await page.evaluate(f'window.scrollTo(0, {scroll_y})')
        await page.wait_for_timeout(120)

        clicked = await page.evaluate('''() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            for (const btn of buttons) {
                const txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                if (txt === 'reply') {
                    const r = btn.getBoundingClientRect();
                    if (r.width > 0 && r.top > 50 && r.top < 750) {
                        btn.click();
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                }
            }
            return null;
        }''')

        if clicked:
            print('Clicked Reply button')
            await page.wait_for_timeout(1500)
            editor = await _wait_for_editor(page)
            if editor:
                return editor
            # give it another second
            await page.wait_for_timeout(1000)
            editor = await _wait_for_editor(page)
            if editor:
                return editor

    print('Could not find Reply button')
    return None


async def _type_and_submit(page, editor_coords, text):
    """
    Type text into the editor at editor_coords and submit.
    Returns True on likely success.
    """
    clean = text.strip().replace('\n\n', ' ').replace('\n', ' ')

    # Click the editor to ensure focus
    await page.mouse.click(editor_coords['x'], editor_coords['y'])
    await page.wait_for_timeout(500)

    # Select-all then delete to clear any placeholder text that may be in the DOM
    await page.keyboard.press('Control+a')
    await page.wait_for_timeout(100)
    await page.keyboard.press('Delete')
    await page.wait_for_timeout(200)

    # Type the comment
    await page.keyboard.type(clean, delay=14)
    await page.wait_for_timeout(800)

    # Verify something was typed
    typed_len = await page.evaluate('''() => {
        const eds = document.querySelectorAll('[contenteditable="true"]');
        for (const ed of eds) {
            const t = ed.innerText || ed.textContent || '';
            if (t.trim().length > 5) return t.trim().length;
        }
        return 0;
    }''')
    print(f'Characters in editor: {typed_len}')

    if typed_len == 0:
        print('Nothing typed — aborting')
        return False

    # Rate-limit check before submit
    if await check_rate_limit(page):
        await page.keyboard.press('Escape')
        return False

    # Re-click editor then submit via Ctrl+Enter
    await page.mouse.click(editor_coords['x'], editor_coords['y'])
    await page.wait_for_timeout(200)
    await page.keyboard.press('Control+Enter')
    await page.wait_for_timeout(2000)

    # Belt-and-suspenders: also click the Comment / Save button if visible
    btn_clicked = await page.evaluate('''() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        for (const btn of buttons) {
            const t = (btn.innerText || btn.textContent || '').trim().toLowerCase();
            if ((t === 'comment' || t === 'save') && !btn.disabled) {
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.top > 0 && r.top < 900) {
                    btn.click();
                    return t;
                }
            }
        }
        return null;
    }''')
    if btn_clicked:
        print(f'Also clicked "{btn_clicked}" button')

    await page.wait_for_timeout(3000)
    await check_rate_limit(page)
    return True


async def post_comment(page, post_url, reply_text, is_reply_to_comment=False):
    """Navigate to post, open the right composer, type and submit."""
    try:
        print(f'Going to: {post_url[:80]}')
        await page.goto(post_url, wait_until='domcontentloaded')
        await page.wait_for_timeout(5000)

        # Bail early if Reddit is already rate-limiting us on page load
        if await check_rate_limit(page):
            print('Rate limited on page load — aborting this post')
            return False

        if is_reply_to_comment:
            editor = await _open_reply_composer(page)
        else:
            editor = await _open_post_composer(page)

        if not editor:
            print('Could not open composer — skipping')
            return False

        success = await _type_and_submit(page, editor, reply_text)
        if success:
            print('Comment posted!')
        return success

    except Exception as e:
        print(f'Error posting: {str(e)[:150]}')
        return False


# ---------------------------------------------------------------------------
# Relevance filtering — tightened to prompting/AI-output focus
# ---------------------------------------------------------------------------

# Hard keyword gate: post must contain at least one of these to even be considered
PROMPT_KEYWORDS = [
    'prompt', 'prompts', 'prompting', 'system prompt', 'context window',
    'tokens', 'token limit', 'ai output', 'ai outputs', 'llm output',
    'getting better results', 'consistent results', 'inconsistent',
    'cursor', 'lovable', 'claude', 'chatgpt', 'gpt-4', 'gpt4',
    'midjourney', 'stable diffusion', 'vibe cod',
    'save my prompts', 'reuse prompts', 'losing prompts', 'prompt library',
    'prompt template', 'prompt bank',
]

# Posts matching these are almost certainly NOT about prompting — hard reject
ANTI_KEYWORDS = [
    'hiring', 'job posting', 'salary', 'looking for work', 'resume',
    'stock price', 'acquisition', 'lawsuit', 'terms of service',
    'data breach', 'privacy policy', 'earnings report',
    'how do i invest', 'crypto', 'nft',
    'motivational', 'just shipped', 'i built a', 'launched my',
    'show hn', 'feedback on my',
]


def passes_keyword_gate(post_text: str) -> bool:
    lower = post_text.lower()
    if not any(kw in lower for kw in PROMPT_KEYWORDS):
        return False
    if any(kw in lower for kw in ANTI_KEYWORDS):
        return False
    return True


async def process_post(page, post):
    post_text = post['title'] + ' ' + post['body']

    # Gate 1: keyword check (fast, no model call)
    if not passes_keyword_gate(post_text):
        print(f'Keyword gate failed: {post["title"][:60]}')
        return False

    # Gate 2: semantic relevance
    if not is_relevant(post_text):
        print(f'Semantic filter failed: {post["title"][:60]}')
        return False

    print(f'Relevant: {post["title"][:60]}')

    if already_replied(post['id']):
        print('Already replied — skipping')
        return False

    comments = await get_comments(page, post['url'])

    if not comments:
        # ── No comments yet: reply directly to the post ──────────────────
        print('No comments — posting top-level comment')
        reply = generate_reply(post['title'], post['body'], '', post['subreddit'])
        if not reply:
            return False
        print(f'Draft reply: {reply[:120]}')
        score = score_reply(post['title'], reply)
        if score < 4:
            print(f'Score {score}/5 — too low, skipping')
            return False
        success = await post_comment(page, post['url'], reply, is_reply_to_comment=False)
        if success:
            mark_replied(post['id'])
            return True
    else:
        # ── Has comments: reply to the first relevant one ────────────────
        for comment in comments:
            key = post['id'] + '_' + comment['id']
            if already_replied(key):
                continue
            if not is_relevant(comment['body']):
                continue
            reply = generate_reply(post['title'], post['body'], comment['body'], post['subreddit'])
            if not reply:
                continue
            print(f'Draft reply: {reply[:120]}')
            score = score_reply(comment['body'], reply)
            if score < 4:
                print(f'Score {score}/5 — too low, skipping')
                continue
            success = await post_comment(page, post['url'], reply, is_reply_to_comment=True)
            if success:
                mark_replied(key)
                return True

    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run():
    while True:
        try:
            async with async_playwright() as p:
                context, page = await make_context(p)
                await login(page)
                print(f'Bot started — {len(SUBREDDITS)} subreddits')
                while True:
                    shuffled = SUBREDDITS.copy()
                    random.shuffle(shuffled)
                    for subreddit in shuffled:
                        print(f'\nChecking r/{subreddit}...')
                        posts = await get_new_posts(page, subreddit)
                        for post in posts:
                            if post['age_hours'] > 2:
                                continue
                            posted = await process_post(page, post)
                            if posted:
                                # Check for rate limit banner immediately after posting
                                rate_hit = await check_rate_limit(page)
                                if not rate_hit:
                                    delay = random.randint(250, 350)
                                    print(f'Posted! Waiting {delay}s...')
                                    await asyncio.sleep(delay)
                                # if rate_hit, check_rate_limit already slept the full time
                    print('\nCycle done — waiting 5 min...')
                    await asyncio.sleep(420)
        except Exception as e:
            print(f'Top-level error, restarting: {str(e)[:100]}')
            await asyncio.sleep(15)


if __name__ == '__main__':
    asyncio.run(run())