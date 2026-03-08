import { useState } from 'react';
import Dashboard  from './pages/Dashboard';
import Keywords   from './pages/Keywords';
import History    from './pages/History';
import Analytics  from './pages/Analytics';
import Settings   from './pages/Settings';
import BotStatus  from './components/BotStatus';

const NAV = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'keywords',  label: 'Keywords'  },
  { id: 'history',   label: 'History'   },
  { id: 'analytics', label: 'Analytics' },
  { id: 'settings',  label: 'Settings'  },
];

export default function App() {
  const [page, setPage] = useState('dashboard');

  const pages = {
    dashboard: <Dashboard />,
    keywords:  <Keywords  />,
    history:   <History   />,
    analytics: <Analytics />,
    settings:  <Settings  />,
  };

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <div className="sidebar-logo">FV</div>
        {NAV.map(n => (
          <button
            key={n.id}
            className={`nav-btn ${page === n.id ? 'active' : ''}`}
            onClick={() => setPage(n.id)}
          >
            {n.label}
          </button>
        ))}
        <div className="sidebar-bottom">
          <BotStatus />
        </div>
      </nav>
      <main className="page-content">
        {pages[page]}
      </main>
    </div>
  );
}
