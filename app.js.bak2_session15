/* === HERMES INTELLIGENCE TERMINAL — Data & Rendering === */

const DATA_URL = 'data.json';
const FALLBACK_DATA = {
  last_sync: new Date().toISOString(),
  regime: {
    bias: "LONG",
    conviction: "HIGH",
    history: [
      { day: "M", val: 1 }, { day: "T", val: 1 }, { day: "W", val: 0 },
      { day: "T", val: 1 }, { day: "F", val: 1 }, { day: "S", val: 1 }, { day: "S", val: -1 }
    ]
  },
  sectors: [
    { name: "DEFI", status: "BULLISH", desc: "TVL +2.3%  |  Aave v4 launch" },
    { name: "AI", status: "NEUTRAL", desc: "TAO consolidating  |  FET range" },
    { name: "PERPS", status: "BULLISH", desc: "OI rising  |  Funding normal" },
    { name: "LENDING", status: "CAUTIOUS", desc: "Rates climbing  |  Risk watch" },
    { name: "DEX", status: "NEUTRAL", desc: "Volume flat  |  No catalyst" }
  ],
  performance: {
    wr: 58, trades: 23, rr: "2.4x", streak: "+3W", pnl: "+$18.40",
    long_wr: 62, short_wr: 41
  },
  memo: {
    regime_insight: "Market in early-cycle accumulation. BTC holding above $104k with decreasing volatility. Altcoin rotation into DeFi blue-chips signals institutional positioning.",
    signal_trust: "High confidence: composite_momentum_T12 on AERO (backtest WR 67%, aligned with sector thesis). Medium: VIRTUAL volume breakout (T6, thin depth — monitor closely).",
    blind_spots: "Funding rates near zero across board. Could signal calm or exhaustion. Watch BTC.D for rotation. BRETT exposure concentrated — single-token risk.",
    adjustment: "Tighten VIRTUAL SL to -2.2% (depth). Skip BRETT T6."
  },
  signals: [
    { name: "composite_mom_T12", token: "AERO", conf: "72%", dir: "LONG", time: "14:02", status: "ACTIVE" },
    { name: "vol_breakout_T6", token: "VIRTUAL", conf: "61%", dir: "LONG", time: "14:02", status: "ACTIVE" },
    { name: "mean_rev_T24", token: "AIXBT", conf: "58%", dir: "SHORT", time: "12:02", status: "GATED" },
    { name: "momentum_div_T12", token: "MORPHO", conf: "55%", dir: "LONG", time: "12:02", status: "WAIT" },
    { name: "oi_surge_T6", token: "BRETT", conf: "48%", dir: "LONG", time: "10:02", status: "REJECTED" },
    { name: "funding_flip_T12", token: "VVV", conf: "43%", dir: "SHORT", time: "08:02", status: "BLACKLIST" },
    { name: "depth_squeeze_T6", token: "AERO", conf: "67%", dir: "LONG", time: "06:02", status: "FILLED" },
    { name: "rsi_div_T24", token: "VIRTUAL", conf: "52%", dir: "LONG", time: "04:02", status: "EXPIRED" }
  ],
  tokens: [
    { name: "AERO", tier: "A", score: 78, sparkline: [40,45,42,55,60,72,68,75,78,76,78] },
    { name: "VIRTUAL", tier: "A", score: 71, sparkline: [50,48,52,55,60,58,65,68,71,70,71] },
    { name: "AIXBT", tier: "B", score: 63, sparkline: [70,65,60,55,58,62,60,63,63,62,63] },
    { name: "MORPHO", tier: "B", score: 59, sparkline: [45,50,48,52,55,58,56,59,59,58,59] },
    { name: "BRETT", tier: "B", score: 45, sparkline: [55,52,50,48,46,44,45,44,45,44,45] },
    { name: "VVV", tier: "C", score: 32, sparkline: [60,55,50,45,40,38,35,33,32,31,32] }
  ],
  convergence: [
    { token: "AERO", score: 82, desc: "momentum + funding + OI aligned", horizon: "T12", features: "3/3 features" },
    { token: "VIRTUAL", score: 67, desc: "volume + momentum convergence", horizon: "T6", features: "2/3 features" },
    { token: "MORPHO", score: 44, desc: "partial: momentum only", horizon: "T12", features: "1/3 features" }
  ],
  health: [
    { name: "Agent VPS", status: "ONLINE", color: "green" },
    { name: "Delta VPS", status: "ONLINE", color: "green" },
    { name: "Venice API", status: "OK", color: "green" },
    { name: "Hyperliquid", status: "CONNECTED", color: "green" },
    { name: "Redis", status: "ACTIVE", color: "green" },
    { name: "Forensics", status: "IDLE", color: "cyan" }
  ],
  news: [
    {title:"The DeFi Moment for Prediction Markets",source:"Chainlink Blog",sentiment:"neutral",sectors:["defi"],is_defi:true,is_ai:false},
    {title:"Aave V4 Launches With Unified Liquidity Layer",source:"The Block",sentiment:"bullish",sectors:["defi","lending"],is_defi:true,is_ai:false},
    {title:"TAO Network Announces Compute Subnet Upgrade",source:"CryptoPanic",sentiment:"bullish",sectors:["ai"],is_defi:false,is_ai:true},
    {title:"Funding Rates Reset Across Major Perps",source:"Coinglass",sentiment:"neutral",sectors:["perps"],is_defi:false,is_ai:false},
    {title:"MorphoLabs Treasury Diversification Proposal",source:"Governance Forum",sentiment:"neutral",sectors:["defi","lending"],is_defi:true,is_ai:false},
    {title:"Base DEX Volume Hits New Monthly High",source:"DeFiLlama",sentiment:"bullish",sectors:["dex"],is_defi:true,is_ai:false}
  ],
  positions: [],
  uptime: "14d 7h"
};

function colorForScore(score) {
  if (score >= 60) return 'var(--green)';
  if (score >= 40) return 'var(--cyan)';
  return 'var(--red)';
}

function colorForBias(bias) {
  if (bias === 'LONG') return 'var(--green)';
  if (bias === 'SHORT') return 'var(--red)';
  return 'var(--grey)';
}

function statusClass(s) {
  return s.toLowerCase().replace(/\s+/g, '-');
}

function renderSparkline(data, color) {
  if (!data || data.length < 2) return '';
  const w = 180, h = 18, pad = 2;
  const mn = Math.min(...data), mx = Math.max(...data);
  const rng = Math.max(mx - mn, 1);
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - mn) / rng) * (h - 2 * pad);
    return `${x},${y}`;
  });
  const areaPath = `M${pts[0]} ${pts.slice(1).map(p => `L${p}`).join(' ')} L${w - pad},${h} L${pad},${h} Z`;
  const linePath = `M${pts[0]} ${pts.slice(1).map(p => `L${p}`).join(' ')}`;
  const last = pts[pts.length - 1].split(',');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${areaPath}" fill="${color}" opacity="0.08"/>
    <path d="${linePath}" fill="none" stroke="${color}" stroke-width="1.5" opacity="0.7"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2.5" fill="${color}"/>
  </svg>`;
}

function render(data) {
  // Sync time
  const sync = new Date(data.last_sync);
  document.getElementById('sync-time').textContent =
    `${String(sync.getUTCHours()).padStart(2,'0')}:${String(sync.getUTCMinutes()).padStart(2,'0')} UTC`;

  // Regime
  const biasColor = colorForBias(data.regime.bias);
  const biasEl = document.getElementById('regime-bias');
  biasEl.textContent = data.regime.bias;
  biasEl.style.color = biasColor;
  document.getElementById('regime-conviction').textContent = `Conviction: ${data.regime.conviction}`;

  const glow = document.getElementById('regime-glow');
  const dot = document.getElementById('regime-dot');
  const glowColor = data.regime.bias === 'LONG' ? '0,255,136' : (data.regime.bias === 'SHORT' ? '255,68,102' : '120,130,155');
  glow.style.background = `radial-gradient(circle, rgba(${glowColor},0.2) 0%, transparent 70%)`;
  dot.style.background = biasColor;
  dot.style.boxShadow = `0 0 12px rgba(${glowColor},0.6), 0 0 24px rgba(${glowColor},0.3)`;

  // History bars
  const hb = document.getElementById('history-bars');
  hb.innerHTML = data.regime.history.map(h => {
    const cls = h.val === 1 ? 'long' : (h.val === -1 ? 'short' : 'neutral');
    return `<div class="history-bar ${cls}">${h.day}</div>`;
  }).join('');

  // Sectors
  const sec = document.getElementById('sectors');
  sec.innerHTML = data.sectors.map(s => {
    const cls = s.status.toLowerCase();
    const borderColor = cls === 'active' ? 'var(--green)' : (cls === 'watch' ? 'var(--amber)' : (cls === 'bullish' ? 'var(--green)' : (cls === 'cautious' ? 'var(--amber)' : (cls === 'bearish' ? 'var(--red)' : 'var(--grey)'))));
    return `<div class="sector-card" style="border-left-color:${borderColor}">
      <div class="sector-top">
        <span class="sector-name">${s.name}</span>
        <span class="sector-badge ${cls}">${s.status}</span>
      </div>
      <div class="sector-desc">${s.desc}</div>
    </div>`;
  }).join('');

  // Performance
  const p = data.performance;
  document.getElementById('wr-value').textContent = `${p.wr}%`;
  const gaugeLen = 157 * p.wr / 100;
  document.getElementById('gauge-fill').setAttribute('stroke-dasharray', `${gaugeLen} 157`);
  const gaugeColor = p.wr >= 50 ? 'var(--green)' : 'var(--red)';
  document.getElementById('gauge-fill').setAttribute('stroke', gaugeColor);
  document.querySelector('.gauge-value span').style.color = gaugeColor;

  document.getElementById('stat-trades').textContent = p.trades;
  document.getElementById('stat-rr').textContent = p.rr;
  const streakEl = document.getElementById('stat-streak');
  streakEl.textContent = p.streak;
  streakEl.className = 'stat-value ' + (p.streak.startsWith('+') ? 'green' : 'red');
  const pnlEl = document.getElementById('stat-pnl');
  pnlEl.textContent = p.pnl;
  pnlEl.className = 'stat-value ' + (p.pnl.startsWith('+') ? 'green' : 'red');

  document.getElementById('long-wr-bar').style.width = `${p.long_wr}%`;
  document.getElementById('long-wr-pct').textContent = `${p.long_wr}%`;
  document.getElementById('short-wr-bar').style.width = `${p.short_wr}%`;
  document.getElementById('short-wr-pct').textContent = `${p.short_wr}%`;

  // Memo
  const memo = document.getElementById('memo-content');
  memo.innerHTML = `
    <div class="memo-section"><div class="memo-heading regime">REGIME INSIGHT</div><div class="memo-text">${data.memo.regime_insight}</div></div>
    <div class="memo-section"><div class="memo-heading trust">SIGNAL TRUST</div><div class="memo-text">${data.memo.signal_trust}</div></div>
    <div class="memo-section"><div class="memo-heading blind">BLIND SPOTS</div><div class="memo-text">${data.memo.blind_spots}</div></div>
    <div class="memo-section"><div class="memo-heading adjust">ADJUSTMENT</div><div class="memo-text">${data.memo.adjustment}</div></div>
  `;

  // News
  const nl = document.getElementById('news-list');
  const newsItems = data.news || [];
  nl.innerHTML = newsItems.map(n => {
    const tags = n.tags || [];
    const tagHtml = tags.slice(0, 3).map(t => `<span class="news-tag">${t}</span>`).join('');
    const timeStr = n.time_ago || '';
    const sentClass = n.sentiment || 'neutral';
    const tokenHtml = (n.tokens || []).slice(0, 2).map(t => `<span class="news-token">${t}</span>`).join('');
    return `<div class="news-item">
      <div class="news-sentiment ${sentClass}"></div>
      <div class="news-body">
        <div class="news-title">${n.title || ''}</div>
        <div class="news-meta">
          <span class="news-source">${n.source || ''}</span>
          <span class="news-time">${timeStr}</span>
          <span class="news-tags">${tagHtml}${tokenHtml}</span>
        </div>
      </div>
    </div>`;
  }).join('');

  // Signals
  const sr = document.getElementById('signal-rows');
  sr.innerHTML = data.signals.map(s => {
    const dirCls = s.dir.toLowerCase();
    const stCls = statusClass(s.status);
    return `<div class="signal-row">
      <span class="sr-signal">${s.name}</span>
      <span class="sr-token">${s.token}</span>
      <span class="sr-conf">${s.conf}</span>
      <span class="sr-dir ${dirCls}">${s.dir}</span>
      <span class="sr-time">${s.time}</span>
      <span class="sr-horizon">${s.horizon || ''}</span>
      <span class="sr-status ${stCls}">${s.status}</span>
    </div>`;
  }).join('');

  // Tokens
  const tl = document.getElementById('token-list');
  tl.innerHTML = data.tokens.map(t => {
    const color = colorForScore(t.score);
    const tierCls = t.tier.toLowerCase();
    const regime = t.regime || 'NEUTRAL';
    const regimeColor = regime === 'BULL' ? 'var(--green)' : (regime === 'BEAR' ? 'var(--red)' : 'var(--grey)');
    const forensic = t.forensic_z !== undefined ? t.forensic_z.toFixed(1) : '--';
    const bpi = t.bpi_z !== undefined ? t.bpi_z.toFixed(1) : '--';
    const sigCount = t.signals_active || 0;
    const sigBadge = sigCount > 0 ? `<span class="token-sig-count">${sigCount}s</span>` : '';
    return `<div class="token-card">
      <div>
        <div class="token-name">${t.name} ${sigBadge}</div>
        <div class="token-sub" style="color:${regimeColor}">${regime} | F:${forensic} B:${bpi}</div>
      </div>
      <div class="tier-badge ${tierCls}">${t.tier}</div>
      <div class="token-bar-wrap">
        <div class="token-bar"><div class="token-bar-fill" style="width:${t.score}%;background:linear-gradient(90deg,transparent,${color})"></div></div>
        <div class="token-sparkline">${renderSparkline(t.sparkline, color)}</div>
      </div>
      <div class="token-score" style="color:${color}">${t.score}</div>
    </div>`;
  }).join('');

  // Convergence
  const cl = document.getElementById('convergence-list');
  cl.innerHTML = data.convergence.map(c => {
    const color = colorForScore(c.score);
    const borderColor = c.score >= 60 ? 'var(--green)' : 'var(--grey)';
    return `<div class="conv-card" style="border-left-color:${borderColor}">
      <div class="conv-top">
        <div class="conv-left">
          <span class="conv-token">${c.token}</span>
          <span class="conv-horizon">${c.horizon}</span>
          <span class="conv-features">${c.features}</span>
        </div>
        <div class="conv-score" style="color:${color}">${c.score}</div>
      </div>
      <div class="conv-desc">${c.desc}</div>
      <div class="conv-bar"><div class="conv-bar-fill" style="width:${c.score}%;background:${color}"></div></div>
    </div>`;
  }).join('');

  // Health
  const hi = document.getElementById('health-items');
  hi.innerHTML = data.health.map(h => {
    const detail = h.detail ? ` <span class="health-detail">(${h.detail})</span>` : '';
    return `<div class="health-item">
      <span class="health-dot ${h.color}"></span>
      <span class="health-name">${h.name}</span>
      <span class="health-status" style="color:var(--${h.color})">${h.status}${detail}</span>
    </div>`;
  }).join('');

  // Positions / Recent Trades
  const posPanel = document.getElementById('positions-content');
  if (posPanel) {
    const positions = data.positions || [];
    const recentTrades = data.recent_trades || [];

    if (positions.length > 0) {
      posPanel.innerHTML = positions.map(p => {
        const pnlColor = (p.pnl_pct || 0) >= 0 ? 'var(--green)' : 'var(--red)';
        const pnlStr = (p.pnl_pct || 0) >= 0 ? `+${(p.pnl_pct||0).toFixed(2)}%` : `${(p.pnl_pct||0).toFixed(2)}%`;
        const dirCls = (p.side || '').toLowerCase();
        return `<div class="trade-row active-trade">
          <span class="trade-coin">${p.coin}</span>
          <span class="trade-dir ${dirCls}">${p.side}</span>
          <span class="trade-signal">${p.signal || ''}</span>
          <span class="trade-pnl" style="color:${pnlColor}">${pnlStr}</span>
          <span class="trade-badge active">OPEN</span>
        </div>`;
      }).join('');
    } else if (recentTrades.length > 0) {
      posPanel.innerHTML = recentTrades.map(t => {
        const pnlColor = t.pnl_pct >= 0 ? 'var(--green)' : 'var(--red)';
        const pnlStr = t.pnl_pct >= 0 ? `+${t.pnl_pct.toFixed(2)}%` : `${t.pnl_pct.toFixed(2)}%`;
        const dirCls = (t.side || '').toLowerCase();
        const durStr = t.duration > 60 ? `${(t.duration/60).toFixed(1)}h` : `${t.duration}m`;
        return `<div class="trade-row closed-trade">
          <span class="trade-coin">${t.coin}</span>
          <span class="trade-dir ${dirCls}">${t.side}</span>
          <span class="trade-pnl" style="color:${pnlColor}">${pnlStr}</span>
          <span class="trade-dur">${durStr}</span>
          <span class="trade-time">${t.time_ago}</span>
        </div>`;
      }).join('');
    } else {
      posPanel.innerHTML = '<div class="no-data">No positions or recent trades</div>';
    }
  }

  // Uptime
  document.getElementById('uptime').textContent = `UPTIME ${data.uptime}`;
}

async function loadData() {
  try {
    const res = await fetch(DATA_URL + '?t=' + Date.now());
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    render(data);
  } catch {
    render(FALLBACK_DATA);
  }
}

loadData();
setInterval(loadData, 60000);

// Refresh countdown
let lastLoad = Date.now();
function updateCountdown() {
  const el = document.getElementById('refresh-countdown');
  if (!el) return;
  const elapsed = Math.floor((Date.now() - lastLoad) / 1000);
  const remaining = Math.max(0, 60 - elapsed);
  el.textContent = `${remaining}s`;
}
const _origLoadData = loadData;
loadData = async function() {
  await _origLoadData();
  lastLoad = Date.now();
};
setInterval(updateCountdown, 1000);
