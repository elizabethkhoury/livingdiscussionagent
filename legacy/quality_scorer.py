import requests, os, time
from dotenv import load_dotenv

load_dotenv()


def score_reply(post_or_comment_text, reply_text):
    MISTRAL_KEY = os.getenv('MISTRAL_API_KEY')
    prompt = (
        'Rate this Reddit reply on a scale of 1-5.\n\n'
        'Original post/comment:\n' + post_or_comment_text[:400] + '\n\n'
        'Reply:\n' + reply_text + '\n\n'
        'Score criteria:\n'
        '5 = Directly addresses a prompting/AI-output problem, helpful, natural, not spammy\n'
        '4 = Relevant to prompting, reasonably helpful, sounds like a real person\n'
        '3 = Vaguely related but generic or slightly off-topic\n'
        "2 = Off-topic, doesn't really address prompting at all\n"
        '1 = Spam, irrelevant, or clearly promotional\n\n'
        'If the reply is about anything other than prompting, AI outputs, or saving/reusing '
        'prompts, score it 1 or 2 regardless of writing quality.\n\n'
        'Respond ONLY with a single digit 1-5, nothing else.'
    )
    for attempt in range(3):
        try:
            resp = requests.post(
                'https://api.mistral.ai/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + MISTRAL_KEY},
                json={
                    'model': 'mistral-small-latest',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'temperature': 0,
                },
                timeout=30,
            )
            first_char = resp.json()['choices'][0]['message']['content'].strip()[0]
            score = int(first_char)
            print(f'Quality score: {score}/5')
            return score
        except Exception as e:
            print(f'Scorer attempt {attempt + 1} failed, retrying...')
            time.sleep(3)
    return 3  # conservative default — won't auto-pass the ≥4 gate
