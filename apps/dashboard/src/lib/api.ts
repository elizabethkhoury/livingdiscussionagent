const apiBaseUrl = process.env.API_BASE_URL ?? 'http://localhost:8000';

async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error(`API request failed for ${path}`);
  }
  return response.json();
}

export function getApiBaseUrl() {
  return apiBaseUrl;
}

export async function fetchCandidates() {
  return read<
    {
      id: string;
      subreddit: string;
      title: string;
      body: string;
      permalink: string;
      route_product: string | null;
      decision: 'abstain' | 'watch_only' | 'queue_draft';
      abstain_reason: string | null;
      model_confidence: number;
      risk_score: number;
      expected_value: number;
      evaluator_summary: string | null;
      features: {
        feature_payload: {
          depth_score?: number;
        };
      }[];
    }[]
  >('/candidates');
}

export async function fetchDefaultAgent() {
  return read<{ id: string; score: number; state: string }>('/agents/default');
}

export async function fetchAgentHealth(id: string) {
  return read<{
    id: string;
    name: string;
    state: string;
    score: number;
    version: number;
    strict_mode_until: string | null;
    thresholds: Record<string, unknown>;
  }>(`/agents/${id}/health`);
}

export async function fetchAnalytics() {
  return read<{
    queued_drafts: number;
    approvals: number;
    manual_posts: number;
    total_reward: number;
    conversions: number;
    by_product: Record<string, number>;
    by_subreddit: Record<string, number>;
  }>('/analytics');
}

export async function fetchReplay(id: string) {
  return read<{
    candidate_id: string;
    title: string;
    subreddit: string;
    decision: string;
    route_product: string | null;
    trace: Record<string, unknown>;
    drafts: {
      id: string;
      body: string;
      status: string;
      critic_notes: Record<string, unknown>;
      similarity_score: number;
      token_usage: number;
    }[];
  }>(`/replays/${id}`);
}
