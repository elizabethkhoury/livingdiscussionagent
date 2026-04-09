import Link from 'next/link';

import { ApprovalActions } from '@/components/approval-actions';
import { MetricCard } from '@/components/metric-card';
import { Shell } from '@/components/shell';
import { fetchCandidates, getApiBaseUrl } from '@/lib/api';

export default async function QueuePage() {
  const candidates = await fetchCandidates();
  const queued = candidates.filter((candidate) => candidate.decision === 'queue_draft');
  const watched = candidates.filter((candidate) => candidate.decision === 'watch_only');
  const abstained = candidates.filter((candidate) => candidate.decision === 'abstain');
  const apiBaseUrl = getApiBaseUrl();

  return (
    <Shell active="/queue">
      <section className="grid-two">
        <section className="panel">
          <div className="panel-header">
            <h2 className="panel-title">Approval Queue</h2>
            <span className="eyebrow">{queued.length} queued candidates</span>
          </div>
          <div className="panel-body">
            <div className="metric-grid">
              <MetricCard label="Queued" value={queued.length} />
              <MetricCard label="Watch only" value={watched.length} />
              <MetricCard label="Abstained" value={abstained.length} />
            </div>
            <div className="candidate-list">
              {queued.map((candidate) => (
                <article key={candidate.id} className="candidate-card">
                  <div className="candidate-meta">
                    <span className="tag">r/{candidate.subreddit}</span>
                    <span className="tag" data-tone="success">
                      {candidate.route_product}
                    </span>
                    <span className="tag">
                      confidence {candidate.model_confidence.toFixed(2)}
                    </span>
                    <span className="tag">risk {candidate.risk_score.toFixed(2)}</span>
                    <span className="tag">EV {candidate.expected_value.toFixed(2)}</span>
                  </div>
                  <h3 className="candidate-title">{candidate.title}</h3>
                  <div className="candidate-body">{candidate.body || 'No body provided.'}</div>
                  <div className="muted">{candidate.evaluator_summary}</div>
                  <div className="candidate-actions">
                    <Link className="button ghost" href={`/replays/${candidate.id}`}>
                      Open Replay
                    </Link>
                    <Link className="button secondary" href={candidate.permalink} target="_blank">
                      View Thread
                    </Link>
                  </div>
                  <ApprovalActions candidateId={candidate.id} apiBaseUrl={apiBaseUrl} />
                </article>
              ))}
              {queued.length === 0 ? (
                <article className="candidate-card">
                  <div className="candidate-title">Nothing queued right now.</div>
                  <div className="candidate-body">
                    Ingest new Reddit threads from the browser discovery flow and the queue will populate here.
                  </div>
                </article>
              ) : null}
            </div>
          </div>
        </section>
        <section className="panel">
          <div className="panel-header">
            <h2 className="panel-title">Operator Notes</h2>
            <span className="eyebrow">Decision posture</span>
          </div>
          <div className="panel-body">
            <div className="split">
              <div className="metric-card">
                <div className="metric-label">Autonomous posting</div>
                <p className="muted">
                  Approval now queues a browser post job. Replay shows whether the Kernel session
                  posted successfully or failed for review.
                </p>
              </div>
              <div className="metric-card">
                <div className="metric-label">Single-product routing</div>
                <p className="muted">
                  Each queued draft is forced to `prompthunt.me` or `upwordly.ai`, never both.
                </p>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Abstain reasons</div>
              <div className="candidate-list">
                {abstained.slice(0, 5).map((candidate) => (
                  <div key={candidate.id} className="candidate-card">
                    <div className="candidate-title">{candidate.title}</div>
                    <div className="tag" data-tone="alert">
                      {candidate.abstain_reason ?? 'rule_block'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </section>
    </Shell>
  );
}
