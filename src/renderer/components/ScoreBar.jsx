/**
 * ScoreBar — relevance score visual bar for alert cards.
 * score: 0-100
 */
export default function ScoreBar({ score = 0 }) {
  const pct  = Math.min(100, Math.max(0, score));
  const color = pct >= 70 ? '#7AE1FF' : pct >= 50 ? '#ffd264' : '#556070';

  return (
    <div className="score-bar-wrap" title={`Relevance: ${pct}%`}>
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="score-bar-label">{pct}</span>
    </div>
  );
}
