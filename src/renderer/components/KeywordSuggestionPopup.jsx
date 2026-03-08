/**
 * KeywordSuggestionPopup
 * Floating card anchored below a keyword input. Appears when AI suggestions
 * are ready. Non-blocking — user can keep typing while it is visible.
 *
 * Props:
 *   suggestions: Array<{ term, language, english_meaning, context }>
 *   onAdd(term):    called when user clicks [+ Add] for one term
 *   onAddAll():     called when user clicks [+ Add All]
 *   onDismiss():    called when user clicks [Dismiss]
 *   loading: bool   show shimmer state while API call is running
 */

const LANG_TAG = { jp: 'JP', kr: 'KR', cn: 'CN' };

export default function KeywordSuggestionPopup({
  suggestions = [],
  onAdd,
  onAddAll,
  onDismiss,
  loading = false,
}) {
  if (!loading && suggestions.length === 0) return null;

  return (
    <div className="ksp-popup" role="dialog" aria-label="AI keyword suggestions">
      <div className="ksp-header">
        <span className="ksp-icon">✦</span>
        AI found related terms
      </div>

      {loading ? (
        <div className="ksp-shimmer-list">
          {[1, 2, 3].map(i => (
            <div key={i} className="ksp-shimmer-row">
              <div className="ksp-shimmer ksp-shimmer-term" />
              <div className="ksp-shimmer ksp-shimmer-meta" />
            </div>
          ))}
        </div>
      ) : (
        <ul className="ksp-list">
          {suggestions.map((s, i) => (
            <li key={i} className="ksp-item">
              <div className="ksp-term-row">
                <span className="ksp-lang-tag">{LANG_TAG[s.language] ?? s.language.toUpperCase()}</span>
                <span className="ksp-term">{s.term}</span>
              </div>
              <div className="ksp-meta">
                → &quot;{s.english_meaning}&quot;
                <span className="ksp-context"> · {s.context}</span>
              </div>
              <button className="ksp-add-btn" onClick={() => onAdd(s.term)}>
                + Add
              </button>
            </li>
          ))}
        </ul>
      )}

      {!loading && (
        <div className="ksp-footer">
          <button className="ksp-add-all-btn" onClick={onAddAll}>+ Add All</button>
          <button className="ksp-dismiss-btn" onClick={onDismiss}>Dismiss</button>
        </div>
      )}
    </div>
  );
}
