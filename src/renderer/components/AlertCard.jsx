/**
 * AlertCard — unified listing card for both EU and Asia platform listings.
 *
 * EU card:   no translation, show listing language, price already in EUR.
 *            If platform === 'vestiaire' and authentication_status === 'verified'
 *            → show green AUTHENTICATED badge prominently.
 *
 * Asia card: translated title (EN) + original title below, original currency
 *            + EUR equivalent, "Translated from JP/KR/CN" label, score bar,
 *            GPT-4o vision confidence.
 *
 * Both:      platform name, last seen, direct link, Interested/Pass/Purchased.
 */

import ScoreBar from './ScoreBar';

const PLATFORM_LABELS = {
  vinted:         'Vinted',
  vestiaire:      'Vestiaire Collective',
  mercari_jp:     'Mercari JP',
  yahoo_auctions: 'Yahoo Auctions',
  rakuma:         'Rakuma',
  bunjang:        'Bunjang',
  xianyu:         'Xianyu (闲鱼)',
};

const LANG_FLAGS = { JPY: '🇯🇵', KRW: '🇰🇷', CNY: '🇨🇳', EUR: '🇪🇺', GBP: '🇬🇧' };
const LANG_NAMES = { JPY: 'JP', KRW: 'KR', CNY: 'CN', EUR: 'EN', GBP: 'EN' };

const EU_PLATFORMS = new Set(['vinted', 'vestiaire']);

export default function AlertCard({ listing, onMark }) {
  const isEU     = EU_PLATFORMS.has(listing.platform);
  const isVerified = listing.platform === 'vestiaire' &&
                     listing.authentication_status === 'verified';

  const platformLabel = PLATFORM_LABELS[listing.platform] ?? listing.platform;
  const priceEUR = listing.price_eur != null
    ? `€${listing.price_eur.toFixed(0)}`
    : null;

  return (
    <article className={`alert-card ${isEU ? 'eu' : 'asia'} ${listing.is_suspicious ? 'suspicious' : ''}`}>

      {/* Thumbnail */}
      {listing.image_url && (
        <div className="card-thumb">
          <img src={listing.image_url} alt="" loading="lazy" />
          {isVerified && (
            <div className="auth-badge">✓ AUTHENTICATED</div>
          )}
        </div>
      )}

      <div className="card-body">

        {/* Platform + timestamp */}
        <div className="card-meta-top">
          <span className="card-platform">{platformLabel}</span>
          {listing.last_seen && (
            <span className="card-ts">{listing.last_seen}</span>
          )}
        </div>

        {/* Title block */}
        {isEU ? (
          <div className="card-title-block">
            <div className="card-title">{listing.title}</div>
            {listing.condition && (
              <span className="card-condition">{listing.condition}</span>
            )}
            <span className="card-lang-tag">
              {LANG_FLAGS[listing.currency] ?? ''} {LANG_NAMES[listing.currency] ?? 'EN'}
            </span>
          </div>
        ) : (
          <div className="card-title-block">
            <div className="card-title">{listing.translated_title ?? listing.title}</div>
            {listing.title !== listing.translated_title && (
              <div className="card-original-title">{listing.title}</div>
            )}
            <span className="card-translated-label">
              Translated from {LANG_NAMES[listing.currency] ?? '?'}
              {LANG_FLAGS[listing.currency] && ` ${LANG_FLAGS[listing.currency]}`}
            </span>
          </div>
        )}

        {/* Price */}
        <div className="card-price-row">
          {isEU ? (
            <span className="card-price">{priceEUR}</span>
          ) : (
            <>
              <span className="card-price">{priceEUR}</span>
              {listing.price && listing.currency && (
                <span className="card-price-orig">
                  ({listing.price.toLocaleString()} {listing.currency})
                </span>
              )}
            </>
          )}
          {listing.is_suspicious && (
            <span className="card-suspicious">⚠ Suspicious price</span>
          )}
        </div>

        {/* Asia-only: score bar + vision confidence */}
        {!isEU && (
          <div className="card-scores">
            {listing.score != null && <ScoreBar score={listing.score} />}
            {listing.vision_confidence != null && (
              <span className="card-vision">
                Vision: {listing.vision_confidence}%
              </span>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="card-actions">
          <button
            className="card-link-btn"
            onClick={() => window.shell.openExternal(listing.url)}
          >
            View listing ↗
          </button>
          <button className="card-action interested" onClick={() => onMark?.(listing, 'interested')}>
            Interested
          </button>
          <button className="card-action pass"       onClick={() => onMark?.(listing, 'pass')}>
            Pass
          </button>
          <button className="card-action purchased"  onClick={() => onMark?.(listing, 'purchased')}>
            Purchased
          </button>
        </div>

      </div>
    </article>
  );
}
