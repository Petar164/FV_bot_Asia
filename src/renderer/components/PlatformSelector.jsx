/**
 * PlatformSelector — checkboxes for choosing which platforms to scrape
 * per keyword group.
 *
 * Props:
 *   selected: { eu: string[], asia: string[] }
 *   onChange: (updated: { eu: string[], asia: string[] }) => void
 */

const EU_PLATFORMS = [
  { id: 'vinted',    label: 'Vinted'                },
  { id: 'vestiaire', label: 'Vestiaire Collective'  },
];

const ASIA_PLATFORMS = [
  { id: 'mercari_jp',     label: 'Mercari JP'           },
  { id: 'yahoo_auctions', label: 'Yahoo Auctions Japan' },
  { id: 'rakuma',         label: 'Rakuma'               },
  { id: 'bunjang',        label: 'Bunjang'              },
  { id: 'xianyu',         label: 'Xianyu'               },
];

export default function PlatformSelector({ selected, onChange }) {
  const eu   = selected?.eu   ?? [];
  const asia = selected?.asia ?? [];

  const toggle = (region, id) => {
    const arr   = region === 'eu' ? [...eu] : [...asia];
    const idx   = arr.indexOf(id);
    if (idx >= 0) arr.splice(idx, 1); else arr.push(id);
    onChange(region === 'eu'
      ? { eu: arr, asia }
      : { eu, asia: arr }
    );
  };

  const setAll = (region, ids) => {
    onChange(region === 'eu' ? { eu: ids, asia } : { eu, asia: ids });
  };

  const setNone = () => onChange({ eu: [], asia: [] });

  return (
    <div className="platform-selector">
      <div className="ps-header">Platforms to scrape</div>

      <div className="ps-region">
        <div className="ps-region-label">EU</div>
        {EU_PLATFORMS.map(p => (
          <label key={p.id} className="ps-item">
            <input
              type="checkbox"
              checked={eu.includes(p.id)}
              onChange={() => toggle('eu', p.id)}
            />
            {p.label}
          </label>
        ))}
      </div>

      <div className="ps-region">
        <div className="ps-region-label">ASIA</div>
        {ASIA_PLATFORMS.map(p => (
          <label key={p.id} className="ps-item">
            <input
              type="checkbox"
              checked={asia.includes(p.id)}
              onChange={() => toggle('asia', p.id)}
            />
            {p.label}
          </label>
        ))}
      </div>

      <div className="ps-actions">
        <button onClick={() => setAll('eu', EU_PLATFORMS.map(p => p.id))}>All EU</button>
        <button onClick={() => setAll('asia', ASIA_PLATFORMS.map(p => p.id))}>All Asia</button>
        <button onClick={() => {
          setAll('eu', EU_PLATFORMS.map(p => p.id));
          onChange({ eu: EU_PLATFORMS.map(p => p.id), asia: ASIA_PLATFORMS.map(p => p.id) });
        }}>All</button>
        <button onClick={setNone}>None</button>
      </div>
    </div>
  );
}
