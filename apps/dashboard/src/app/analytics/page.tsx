import { MetricCard } from '@/components/metric-card';
import { Shell } from '@/components/shell';
import { fetchAnalytics } from '@/lib/api';

export default async function AnalyticsPage() {
  const analytics = await fetchAnalytics();

  return (
    <Shell active="/analytics">
      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">Analytics</h2>
          <span className="eyebrow">Sparse reward, dense visibility</span>
        </div>
        <div className="panel-body">
          <div className="metric-grid">
            <MetricCard label="Queued drafts" value={analytics.queued_drafts} />
            <MetricCard label="Approvals" value={analytics.approvals} />
            <MetricCard label="Manual posts" value={analytics.manual_posts} />
            <MetricCard label="Reward total" value={analytics.total_reward.toFixed(2)} />
            <MetricCard label="Conversions" value={analytics.conversions} />
          </div>
          <div className="split">
            <div className="metric-card">
              <div className="metric-label">By product</div>
              <pre className="trace-box">{JSON.stringify(analytics.by_product, null, 2)}</pre>
            </div>
            <div className="metric-card">
              <div className="metric-label">By subreddit</div>
              <pre className="trace-box">{JSON.stringify(analytics.by_subreddit, null, 2)}</pre>
            </div>
          </div>
        </div>
      </section>
    </Shell>
  );
}
