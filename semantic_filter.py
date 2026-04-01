from sentence_transformers import SentenceTransformer
import chromadb

model = SentenceTransformer('BAAI/bge-small-en-v1.5')
client = chromadb.Client()
collection = client.get_or_create_collection('prompthunt_topics_v2')

# Tightly scoped to prompting pain points and prompt management
TOPICS = [
    # Prompt loss / rewriting pain
    'I keep losing my AI prompts and have to rewrite them every time',
    'I spend hours rewriting the same prompts from scratch every week',
    'where do you store and save your best prompts',
    'how do you keep track of prompts that worked well',
    'best way to save and organize AI prompts so you can reuse them',

    # Writing better prompts
    'how do I write better prompts for ChatGPT or Claude',
    'my prompts give completely different results every time I run them',
    'how to get consistent reliable outputs from ChatGPT',
    'tips for writing prompts that actually work every time',
    'prompt engineering tips for getting better AI outputs',
    'prompt templates that reliably produce good results',
    'how to structure a prompt to stop AI from going off-track',

    # Wasted credits / tokens
    'wasting tokens because my prompts are too vague',
    'burning through API credits because prompts keep failing',
    'how to write prompts that use fewer tokens but get better results',
    'optimizing prompts to save money on ChatGPT API calls',
    'reducing hallucinations by improving my system prompt',

    # Tool-specific prompting issues
    'Cursor AI not following my instructions in the prompt',
    'Lovable keeps producing wrong code because my prompts are unclear',
    'Claude ignoring context in my prompt how to fix',
    'ChatGPT misunderstanding my prompts every single time',
    'Midjourney prompt tips to get consistent image style',
    'stable diffusion prompts for consistent character style',
    'vibe coding prompts for Cursor that actually produce good code',
    'how to write better prompts for AI coding assistants',
    'system prompt tips to make Claude or ChatGPT do exactly what I want',

    # Finding and sharing prompts
    'where can I find proven prompts that actually work',
    'sharing prompts that gave amazing results',
    'is there a library of good AI prompts I can search',
    'looking for a database of prompts for different use cases',
    'best community for sharing and discovering AI prompts',

    # Context window and memory
    'AI keeps forgetting context between sessions how to fix prompts',
    'Claude Code losing context how to write prompts to preserve memory',
    'how to write prompts so the AI remembers instructions across messages',
]

embeddings = model.encode(TOPICS).tolist()
collection.add(
    documents=TOPICS,
    embeddings=embeddings,
    ids=[f'topic_{i}' for i in range(len(TOPICS))]
)

# Raised threshold — only engage when clearly on-topic
THRESHOLD = 0.44

def is_relevant(post_text, threshold=THRESHOLD):
    embedding = model.encode([post_text]).tolist()
    results = collection.query(query_embeddings=embedding, n_results=1)
    score = 1 - results['distances'][0][0]
    print(f'Relevance score: {score:.3f} (need ≥{threshold})')
    return score >= threshold