/**
 * Dashboard page — embeds the existing Three.js globe dashboard via an
 * <iframe> pointing at the FastAPI server, plus a live alert feed.
 *
 * When the Electron app starts the Python bot, the FastAPI dashboard is
 * available at localhost:8888.  We render it in an iframe so the full
 * Three.js globe works without re-implementing it in React.
 */

import { useState, useEffect } from 'react';
import AlertCard from '../components/AlertCard';

const DASHBOARD_URL = 'http://127.0.0.1:8888';

export default function Dashboard() {
  const [alerts, setAlerts]   = useState([]);
  const [botUp,  setBotUp]    = useState(false);

  useEffect(() => {
    // Listen for new listings from the bot process
    window.bot.onMessage(msg => {
      if (msg.type === 'new_listing') {
        setAlerts(prev => [msg.listing, ...prev].slice(0, 200));
      }
      if (msg.type === 'status') {
        setBotUp(msg.status === 'running');
      }
    });
  }, []);

  return (
    <div className="dashboard-page">
      {/* Globe panel — full-screen FastAPI dashboard in iframe */}
      <div className="globe-panel">
        {botUp ? (
          <iframe
            src={DASHBOARD_URL}
            title="FashionVoid Globe"
            className="globe-iframe"
            sandbox="allow-scripts allow-same-origin"
          />
        ) : (
          <div className="globe-placeholder">
            <p>Start the bot to load the globe dashboard</p>
          </div>
        )}
      </div>

      {/* Live alert feed */}
      {alerts.length > 0 && (
        <aside className="alert-feed">
          <div className="feed-header">Live alerts ({alerts.length})</div>
          <div className="feed-list">
            {alerts.map((l, i) => (
              <AlertCard
                key={`${l.platform}-${l.id}-${i}`}
                listing={l}
                onMark={(listing, action) => console.log('mark', listing.id, action)}
              />
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
