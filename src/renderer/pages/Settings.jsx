/**
 * Settings page — read-only view of the active config.
 * Editing is done directly in config.yaml for now.
 */

import { useState, useEffect } from 'react';

const API = 'http://127.0.0.1:8888/api/config';

export default function Settings() {
  const [cfg,     setCfg]     = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(API)
      .then(r => r.json())
      .then(data => { setCfg(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading">Loading config…</div>;

  return (
    <div className="settings-page">
      <h2 className="page-title">Settings</h2>
      <p className="settings-hint">
        Edit <code>config.yaml</code> to change settings, then restart the bot.
      </p>

      {cfg && (
        <div className="settings-sections">
          <Section title="Translation">
            <Row label="Primary"   value={cfg.translation?.primary ?? '—'} />
            <Row label="DeepL"     value={cfg.translation?.deepl_api_key ? '✓ configured' : '✗ not set'} />
            <Row label="Google"    value={cfg.translation?.google_api_key ? '✓ configured' : '✗ not set'} />
          </Section>

          <Section title="OpenAI">
            <Row label="API Key"       value={cfg.openai?.api_key ? '✓ configured' : '✗ not set'} />
            <Row label="Vision model"  value={cfg.openai?.vision_model ?? '—'} />
            <Row label="Vision filter" value={cfg.openai?.vision_enabled ? 'enabled' : 'disabled'} />
          </Section>

          <Section title="Alerts">
            <Row label="Email"     value={cfg.alerts?.email?.enabled    ? 'enabled' : 'disabled'} />
            <Row label="SMS"       value={cfg.alerts?.sms?.enabled      ? 'enabled' : 'disabled'} />
            <Row label="WhatsApp"  value={cfg.alerts?.sms?.whatsapp_enabled ? 'enabled' : 'disabled'} />
            <Row label="Push"      value={cfg.alerts?.push?.enabled     ? `enabled (${cfg.alerts.push.ntfy_topic})` : 'disabled'} />
          </Section>

          <Section title="Proxies">
            <Row label="Enabled" value={cfg.proxies?.enabled ? 'yes' : 'no'} />
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="settings-section">
      <div className="settings-section-title">{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="settings-row">
      <span className="settings-key">{label}</span>
      <span className="settings-val">{value}</span>
    </div>
  );
}
