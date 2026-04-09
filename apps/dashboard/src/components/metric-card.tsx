export function MetricCard({
  label,
  value,
}: Readonly<{
  label: string;
  value: string | number;
}>) {
  return (
    <article className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </article>
  );
}
