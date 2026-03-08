/**
 * Analytics page — summary stats from the FastAPI /api/stats endpoint.
 * Scaffold — charts will be added in a future sprint.
 */

import { useState, useEffect } from 'react';

const API = 'http://127.0.0.1:8888/api/stats';

export default function Analytics() {
  const [stats,   setStats]   = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(API)
      .then(r => r.json())
      .then(data => { setStats(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Loading stats…</div>;
  if (!stats)  return <div className="page-loading">Start the bot to see analytics.</div>;

  return (
    <div className="analytics-page">
      <h2 className="page-title">Analytics</h2>

      <div className="stat-grid">
        <StatCard label="Total Listings" value={stats.total_listings ?? 0} />
        <StatCard label="Suspicious"     value={stats.suspicious    ?? 0} accent="orange" />
        <StatCard label="Alerts Sent"    value={stats.alerts_sent   ?? 0} accent="blue" />
        <StatCard label="Platforms"      value={Object.keys(stats.by_platform ?? {}).length} />
      </div>

      <div className="by-platform">
        <h3>By Platform</h3>
        <table className="stats-table">
          <thead>
            <tr><th>Platform</th><th>Listings</th><th>Suspicious</th></tr>
          </thead>
          <tbody>
            {Object.entries(stats.by_platform ?? {}).map(([p, v]) => (
              <tr key={p}>
                <td>{p}</td>
                <td>{v.total    ?? 0}</td>
                <td>{v.suspicious ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }) {
  const color = accent === 'orange' ? '#ff8800' : accent === 'blue' ? '#7AE1FF' : '#c0d8e8';
  return (
    <div className="stat-card">
      <div className="stat-value" style={{ color }}>{value.toLocaleString()}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
