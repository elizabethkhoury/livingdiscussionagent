import { Shell } from '@/components/shell';
import { fetchReplay } from '@/lib/api';

export default async function ReplayPage({
  params,
}: Readonly<{
  params: Promise<{ id: string }>;
}>) {
  const { id } = await params;
  const replay = await fetchReplay(id);

  return (
    <Shell active="/queue">
      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">Replay Trace</h2>
          <span className="eyebrow">Candidate {replay.candidate_id.slice(0, 8)}</span>
        </div>
        <div className="panel-body">
          <div className="candidate-card">
            <div className="candidate-meta">
              <span className="tag">r/{replay.subreddit}</span>
              <span className="tag">{replay.decision}</span>
              {replay.route_product ? <span className="tag">{replay.route_product}</span> : null}
            </div>
            <h3 className="candidate-title">{replay.title}</h3>
          </div>
          <div className="split">
            <div className="metric-card">
              <div className="metric-label">Decision trace</div>
              <pre className="trace-box">{JSON.stringify(replay.trace, null, 2)}</pre>
            </div>
            <div className="metric-card">
              <div className="metric-label">Drafts</div>
              <div className="candidate-list">
                {replay.drafts.map((draft) => (
                  <article key={draft.id} className="candidate-card">
                    <div className="candidate-meta">
                      <span className="tag">{draft.status}</span>
                      <span className="tag">sim {draft.similarity_score.toFixed(2)}</span>
                      <span className="tag">{draft.token_usage} tokens</span>
                    </div>
                    <div className="candidate-body">{draft.body}</div>
                    <pre className="trace-box">{JSON.stringify(draft.critic_notes, null, 2)}</pre>
                  </article>
                ))}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Posting actions</div>
              <div className="candidate-list">
                {replay.actions.map((action) => (
                  <article key={action.id} className="candidate-card">
                    <div className="candidate-meta">
                      <span className="tag">{action.action_type}</span>
                      <span className="tag">{new Date(action.created_at).toLocaleString()}</span>
                    </div>
                    <div className="candidate-body">{action.notes ?? 'No notes recorded.'}</div>
                    {'external_comment_url' in action.payload &&
                    typeof action.payload['external_comment_url'] === 'string' ? (
                      <a
                        className="button ghost"
                        href={action.payload['external_comment_url']}
                        target="_blank"
                      >
                        View Posted Comment
                      </a>
                    ) : null}
                    <pre className="trace-box">{JSON.stringify(action.payload, null, 2)}</pre>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </Shell>
  );
}
