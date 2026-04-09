import { MetricCard } from '@/components/metric-card';
import { Shell } from '@/components/shell';
import { fetchAgentHealth, fetchDefaultAgent } from '@/lib/api';

export default async function HealthPage() {
  const defaultAgent = await fetchDefaultAgent();
  const health = await fetchAgentHealth(defaultAgent.id);

  return (
    <Shell active="/health">
      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">Agent Health</h2>
          <span className="eyebrow">Policy version {health.version}</span>
        </div>
        <div className="panel-body">
          <div className="metric-grid">
            <MetricCard label="State" value={health.state} />
            <MetricCard label="Score" value={health.score.toFixed(2)} />
            <MetricCard
              label="Strict mode until"
              value={health.strict_mode_until ? health.strict_mode_until.slice(0, 10) : 'n/a'}
            />
          </div>
          <div className="split">
            <div className="metric-card">
              <div className="metric-label">Thresholds</div>
              <pre className="trace-box">{JSON.stringify(health.thresholds, null, 2)}</pre>
            </div>
            <div className="metric-card">
              <div className="metric-label">Lifecycle behavior</div>
              <p className="muted">
                The agent enters `stressed` below 25 points and retires when daily reflections
                stay negative under zero. Retirement spawns a new policy version with inherited
                long-term memory.
              </p>
            </div>
          </div>
        </div>
      </section>
    </Shell>
  );
}
