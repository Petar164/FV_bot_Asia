import { useState, useEffect } from 'react';

export default function BotStatus() {
  const [status, setStatus]   = useState('idle');   // idle | running | error
  const [lastLog, setLastLog] = useState('');

  useEffect(() => {
    window.bot.onMessage(msg => {
      if (msg.type === 'status') setStatus(msg.status);
    });
    window.bot.onLog(log => setLastLog(log.slice(0, 80)));
    window.bot.onExit(({ code }) => setStatus(code === 0 ? 'idle' : 'error'));
  }, []);

  const toggle = () => {
    if (status === 'running') {
      window.bot.stop();
      setStatus('idle');
    } else {
      window.bot.start();
      setStatus('running');
    }
  };

  const dot = { idle: '#2e4050', running: '#7AE1FF', error: '#ff4444' }[status];

  return (
    <div className="bot-status">
      <span className="bot-dot" style={{ background: dot }} />
      <span className="bot-label">{status.toUpperCase()}</span>
      <button className="bot-toggle" onClick={toggle}>
        {status === 'running' ? 'Stop' : 'Start'}
      </button>
      {lastLog && <div className="bot-log">{lastLog}</div>}
    </div>
  );
}
