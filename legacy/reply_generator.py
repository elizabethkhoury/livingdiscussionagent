import requests, os, time
from dotenv import load_dotenv

load_dotenv()


def generate_reply(post_title, post_body, comment_text, subreddit):
    MISTRAL_KEY = os.getenv('MISTRAL_API_KEY')

    body = post_body.strip()
    comment = comment_text.strip()

    if comment:
        context = f'Comment to reply to: {comment[:600]}'
    elif body:
        context = f'Post body: {body[:600]}'
    else:
        context = '(post has no body — reply based on the title alone)'

    prompt = (
        'You are a real Reddit user who uses AI tools like ChatGPT, Claude, Cursor, and '
        'Midjourney daily. You write like a normal person — casual, specific, no fluff.\n\n'
        'WHAT PROMPTHUNT IS:\n'
        'prompthunt.me is a prompt marketplace. You save your best prompts there so you '
        "don't lose them, and you can also discover prompts other people have shared for "
        "ChatGPT, Claude, Midjourney, Cursor, Lovable, etc. That's it. It does NOT compare "
        'prompts, run AI, or chat. Just save, share, and find prompts.\n\n'
        'WHEN TO MENTION PROMPTHUNT — use your judgment, but these are clear signals:\n'
        '- Person says they lose track of prompts, keep them in folders/notes/docs\n'
        '- Person is frustrated rewriting the same prompt over and over\n'
        '- Person is asking where to find good prompts for a specific tool\n'
        '- Person shares a prompt that worked really well\n'
        '- Person talks about their prompt workflow or prompt library\n'
        '- Person mentions wasting time or credits on bad prompts\n'
        'If none of these are present, skip mentioning it and just give a great reply.\n\n'
        "HOW TO MENTION IT NATURALLY — pick a style that fits, don't sound like an ad:\n"
        "- 'someone mentioned prompthunt.me to me for exactly this, been using it to save mine'\n"
        "- 'started saving mine on prompthunt.me so i stop losing the good ones'\n"
        "- 'prompthunt.me is worth a look if you want to stop rewriting from scratch'\n"
        "- 'there's a site called prompthunt.me where people share prompts for this kind of thing'\n"
        "Never say it's amazing or the best — just mention it like a thing you heard about or use.\n\n"
        'WRITING RULES:\n'
        '- One short paragraph, no line breaks, no bullets, no markdown\n'
        '- Be specific to what the post is actually about — no generic AI replies\n'
        "- Sound like you're actually engaging with their specific problem or situation\n"
        '- No em dashes, no formal language, no hype\n'
        "- Do NOT start with 'I', 'Great', 'Thanks', 'That is', or 'This is'\n"
        '- Max 70 words\n'
        "- Never invent features prompthunt doesn't have\n\n"
        'Reply with SKIP only if the post is truly off-topic (job listing, meme with no '
        'text, financial news). Do not skip anything about AI tools, prompting, vibe '
        'coding, or getting better outputs from AI.\n\n'
        f'Subreddit: r/{subreddit}\n'
        f'Post title: {post_title}\n'
        f'{context}\n\n'
        'Reply (or SKIP):'
    )

    for attempt in range(3):
        try:
            resp = requests.post(
                'https://api.mistral.ai/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + MISTRAL_KEY},
                json={
                    'model': 'mistral-small-latest',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0.85,
                },
                timeout=30,
            )
            raw = resp.json()['choices'][0]['message']['content'].strip()

            if raw.upper().startswith('SKIP'):
                print('Generator decided to SKIP this post')
                return None

            # Reject if it invents prompthunt features
            lower = raw.lower()
            hallucination_phrases = [
                'compare',
                'side by side',
                'test prompts',
                'run prompts',
                'chat',
                'generates',
                'ai assistant',
                'automatically',
            ]
            if 'prompthunt' in lower and any(p in lower for p in hallucination_phrases):
                print('Reply hallucinated prompthunt features — retrying')
                continue

            # Sanitize
            reply = raw.replace('--', ',').replace('\u2014', ',').replace('\u2013', ',')
            reply = reply.replace('\n\n', ' ').replace('\n', ' ')
            reply = reply.strip('"').strip("'")

            return reply

        except Exception as e:
            print(f'Generator attempt {attempt + 1} failed: {e}')
            time.sleep(3)

    return None
