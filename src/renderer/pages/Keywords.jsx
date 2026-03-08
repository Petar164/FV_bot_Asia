/**
 * Keywords page — manage keyword groups with AI expansion and
 * real-time suggestions while typing.
 */

import { useState, useEffect, useRef } from 'react';
import PlatformSelector        from '../components/PlatformSelector';
import KeywordSuggestionPopup  from '../components/KeywordSuggestionPopup';

export default function Keywords() {
  const [groups,      setGroups]      = useState([]);
  const [activeGroup, setActiveGroup] = useState(null);

  // Suggestion state for the new-term input
  const [inputValue,  setInputValue]  = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [showPopup,   setShowPopup]   = useState(false);
  const [loading,     setLoading]     = useState(false);
  const [dismissed,   setDismissed]   = useState(new Set());
  const debounceRef = useRef(null);

  // ── Debounced suggestion fetch ──────────────────────────────────────────────
  useEffect(() => {
    if (inputValue.length < 3) {
      setShowPopup(false);
      return;
    }
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setShowPopup(true);
      const raw = await window.keywords.getSuggestions(inputValue);
      const fresh = (raw ?? []).filter(s => !dismissed.has(s.term));
      setLoading(false);
      if (fresh.length > 0) {
        setSuggestions(fresh);
      } else {
        setShowPopup(false);
      }
    }, 600);
    return () => clearTimeout(debounceRef.current);
  }, [inputValue]);

  // Clear popup when input cleared
  useEffect(() => {
    if (!inputValue) { setShowPopup(false); setSuggestions([]); }
  }, [inputValue]);

  // ── Suggestion actions ──────────────────────────────────────────────────────
  const addTerm = async (term) => {
    if (activeGroup == null) return;
    await window.keywords.addTerm(activeGroup, term);
    setSuggestions(prev => prev.filter(s => s.term !== term));
    if (suggestions.length <= 1) setShowPopup(false);
  };

  const addAll = async () => {
    for (const s of suggestions) {
      if (activeGroup != null) await window.keywords.addTerm(activeGroup, s.term);
    }
    setShowPopup(false);
    setSuggestions([]);
  };

  const dismiss = () => {
    setDismissed(prev => new Set([...prev, ...suggestions.map(s => s.term)]));
    setShowPopup(false);
    setSuggestions([]);
  };

  return (
    <div className="keywords-page">
      <h2 className="page-title">Keyword Groups</h2>

      {/* Group list */}
      <div className="group-list">
        {groups.length === 0 && (
          <p className="empty-hint">
            No keyword groups configured yet. Add one in config.yaml and restart.
          </p>
        )}
        {groups.map((g, i) => (
          <div
            key={i}
            className={`group-card ${activeGroup === i ? 'active' : ''}`}
            onClick={() => setActiveGroup(i)}
          >
            <div className="group-name">{g.group}</div>
            <div className="group-meta">
              EN: {(g.terms_en ?? []).length} terms ·
              JP: {(g.terms_jp ?? []).length} ·
              KR: {(g.terms_kr ?? []).length} ·
              CN: {(g.terms_cn ?? []).length}
            </div>
            {g.ai_generated && (
              <span className="ai-badge">AI expanded</span>
            )}
            {activeGroup === i && (
              <PlatformSelector
                selected={typeof g.platforms === 'object' && !Array.isArray(g.platforms)
                  ? g.platforms
                  : { eu: [], asia: g.platforms ?? [] }
                }
                onChange={() => {/* TODO: persist via IPC */}}
              />
            )}
          </div>
        ))}
      </div>

      {/* New term input with AI suggestion popup */}
      <div className="add-term-wrap">
        <label className="add-term-label">Add term to group {activeGroup ?? '—'}</label>
        <div className="add-term-row">
          <input
            className="add-term-input"
            placeholder="Type a search term…"
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            disabled={activeGroup == null}
          />
          <button
            className="add-term-btn"
            disabled={!inputValue || activeGroup == null}
            onClick={() => addTerm(inputValue)}
          >
            Add
          </button>
        </div>

        {showPopup && (
          <KeywordSuggestionPopup
            suggestions={suggestions}
            loading={loading}
            onAdd={addTerm}
            onAddAll={addAll}
            onDismiss={dismiss}
          />
        )}
      </div>
    </div>
  );
}
