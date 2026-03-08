/**
 * History page — searchable list of all stored listings.
 * Fetches from the FastAPI /api/listings endpoint.
 */

import { useState, useEffect } from 'react';
import AlertCard from '../components/AlertCard';

const API = 'http://127.0.0.1:8888/api/listings';

export default function History() {
  const [listings, setListings] = useState([]);
  const [query,    setQuery]    = useState('');
  const [platform, setPlatform] = useState('all');
  const [loading,  setLoading]  = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}?limit=200`)
      .then(r => r.json())
      .then(data => { setListings(data.listings ?? data ?? []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const filtered = listings.filter(l => {
    const matchQ = !query || (
      (l.title ?? '').toLowerCase().includes(query.toLowerCase()) ||
      (l.translated_title ?? '').toLowerCase().includes(query.toLowerCase())
    );
    const matchP = platform === 'all' || l.platform === platform;
    return matchQ && matchP;
  });

  const platforms = ['all', ...new Set(listings.map(l => l.platform))];

  return (
    <div className="history-page">
      <h2 className="page-title">History</h2>

      <div className="history-filters">
        <input
          className="filter-input"
          placeholder="Search listings…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <select
          className="filter-select"
          value={platform}
          onChange={e => setPlatform(e.target.value)}
        >
          {platforms.map(p => (
            <option key={p} value={p}>{p === 'all' ? 'All platforms' : p}</option>
          ))}
        </select>
      </div>

      {loading && <div className="loading-hint">Loading…</div>}

      <div className="history-grid">
        {filtered.map((l, i) => (
          <AlertCard key={`${l.platform}-${l.id}-${i}`} listing={l} />
        ))}
        {!loading && filtered.length === 0 && (
          <p className="empty-hint">No listings found.</p>
        )}
      </div>
    </div>
  );
}
