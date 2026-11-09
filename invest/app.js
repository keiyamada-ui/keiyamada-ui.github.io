// ことり投資ノート 共通処理
// - この画面（公開サイト）にはデータを置かない。データは非公開の invest-system から「合い鍵」で直接読む
// - 合い鍵は、この端末（ブラウザ）の中だけに保存する
const REPO = "keiyamada-ui/invest-system";
const OWNER = REPO.split("/")[0];
const API = "https://api.github.com";
const DATA_FILE = "data/jp_latest.json";
const WORKFLOW = "jp_score.yml";
const KEY_NAME = "invest-gh-key";

const STYLE_NAMES = {
  balanced: "バランス", yomi: "億り人流", dividend: "増配重視", quality: "長期優良", value: "割安重視", growth: "成長重視", custom: "マイ配分",
};
const STYLE_DESC = {
  balanced: "6つの観点をバランスよく", yomi: "稼ぐ力×成長×割安（ROE10%↑・PER15↓の考え方）",
  dividend: "ROE−DOE（増配余力）を最重視", quality: "長く持てる健全で質の高い会社", value: "安く買えることを重視",
  growth: "売上・利益の伸びを最重視", custom: "あなたが調整した配分",
};
const FACTOR_KEYS = ["profit", "growth", "value", "dividend", "quality", "safety"];
const FACTOR_SHORT = { profit: "収益", growth: "成長", value: "割安", dividend: "増配", quality: "質", safety: "健全" };
const FACTOR_LONG = { profit: "収益性", growth: "成長性", value: "割安性", dividend: "増配余力", quality: "利益の質", safety: "健全性" };
const FACTOR_HOW = {
  profit: "ROE・営業利益率。稼ぐ力は株価の土台",
  growth: "売上・営業利益・会社予想EPSの伸び",
  value: "予想PER・PBR。低いほど高得点",
  dividend: "ROE−DOE・株主資本の伸び・配当利回り",
  quality: "営業CF÷純利益。利益が現金を伴っているか",
  safety: "自己資本比率。不況に強いか",
};
const BONUS_DESC = {
  "ROE10%↑PER15↓": "ROE10%以上かつ予想PER15倍以下（稼ぐ力があり割高でない）",
  "増収増益": "売上・営業利益が増え、会社予想EPSも増加（成長ストーリーが続いている）",
  "増配余力大": "配当ありで ROE−DOE が8%以上（利益の多くが株主資本に積み上がる）",
  "上方修正": "今期の会社予想（営業利益）を期初から3%以上引き上げた。上方修正する会社は続けて修正しやすい",
  "進捗率が高い": "四半期の時点で通期予想に対する進み具合が標準より10ポイント以上速い（上方修正の候補）",
};
const FLAG_DESC = {
  "特別利益の疑い": "最終利益が営業利益の1.2倍超。資産売却など一時的な利益の可能性",
  "本業赤字": "営業利益がマイナスなのに最終利益はプラス",
  "PER異常に低い": "PER4倍未満。一時的な利益か株式分割による計算のずれの可能性",
  "減益予想": "会社予想EPSが前期実績より20%以上低い",
  "営業CF赤字": "本業で現金が出ていっている",
  "売買が少ない": "1日の売買代金が3,000万円未満で売買しにくい",
  "下方修正": "今期の会社予想（営業利益）を期初から5%以上引き下げた",
};

// ── 小さな道具 ──
function el(tag, attrs = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) sk.startsWith("--") ? n.style.setProperty(sk, String(sv)) : (n.style[sk] = sv);
    }
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c !== null && c !== undefined && c !== false) n.append(c);
  return n;
}
const $ = id => document.getElementById(id);
function toast(msg) {
  let t = $("toast");
  if (!t) { t = el("div", { id: "toast", role: "status" }); document.body.append(t); }
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 2300);
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};

// ── 数字の見せ方 ──
const fmt = {
  pct(v, d = 2) { return v === null || v === undefined ? "–" : (v * 100).toFixed(d) + "%"; },
  x(v) { return v === null || v === undefined ? "–" : v.toFixed(2) + "倍"; },
  yen(v) { return v === null || v === undefined ? "–" : Math.round(v).toLocaleString("ja-JP") + "円"; },
  oku(v) {
    if (v === null || v === undefined) return "–";
    const oku = v / 1e8;
    return oku >= 10000 ? (oku / 10000).toFixed(2) + "兆円" : Math.round(oku).toLocaleString("ja-JP") + "億円";
  },
  date(s) { if (!s) return "–"; const [y, m, d] = s.slice(0, 10).split("-"); return `${+y}年${+m}月${+d}日`; },
  md(s) { if (!s) return "–"; const [, m, d] = s.slice(0, 10).split("-"); return `${+m}/${+d}`; },
};

// ── 合い鍵 ──
const Key = {
  get() { try { return localStorage.getItem(KEY_NAME) || ""; } catch (e) { return ""; } },
  set(v) { try { localStorage.setItem(KEY_NAME, v); } catch (e) {} },
  clear() { try { localStorage.removeItem(KEY_NAME); localStorage.removeItem("invest-key-exp"); } catch (e) {} },
};

async function gh(path, { method = "GET", body, accept } = {}) {
  const key = Key.get();
  if (!key) { const e = new Error("合い鍵が登録されていません"); e.status = 0; throw e; }
  const headers = { Accept: accept || "application/vnd.github+json", Authorization: "Bearer " + key };
  if (body) headers["Content-Type"] = "application/json";
  const r = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
  const exp = r.headers.get("github-authentication-token-expiration");
  if (exp) store.set("invest-key-exp", exp);
  if (!r.ok) {
    let msg = ""; try { msg = (await r.json()).message || ""; } catch (e) {}
    const e = new Error(explain(r.status, msg)); e.status = r.status; throw e;
  }
  if (r.status === 204) return null;
  return accept && accept.includes("raw") ? r.text() : r.json();
}
function explain(status, msg) {
  if (status === 401) return "合い鍵が使えなくなっています（期限切れ・削除など）。「🔑 合い鍵」で登録し直してください";
  if (status === 403 && /rate limit/i.test(msg)) return "読み込みの回数制限に達しました。少し待ってから開き直してください";
  if (status === 403 || status === 404) return "権限が足りないか、データがまだありません。合い鍵の権限と、採点を一度実行したかを確認してください";
  return `うまくいきませんでした（${status} ${msg}）`;
}
function keyDaysLeft() {
  const exp = store.get("invest-key-exp", "");
  if (!exp) return null;
  const t = Date.parse(String(exp).replace(" UTC", "Z").replace(" ", "T"));
  return isNaN(t) ? null : Math.floor((t - Date.now()) / 86400000);
}

// ── データ（最新の採点結果）。前回読んだものをこの端末に残し、すぐ表示 → 裏で最新に更新 ──
const CACHE = "invest-data-v1";
async function cachedJSON(path) {
  try { const r = await (await caches.open(CACHE)).match(path); return r ? r.json() : null; } catch (e) { return null; }
}
async function fetchJSON(path) {
  const text = await gh(`/repos/${REPO}/contents/${path}?ref=main`, { accept: "application/vnd.github.raw+json" });
  try { await (await caches.open(CACHE)).put(path, new Response(text, { headers: { "Content-Type": "application/json" } })); } catch (e) {}
  return JSON.parse(text);
}
// 端末に残っていたデータですぐ表示し、裏で最新を読む。onData は最大2回呼ばれる
async function loadJSON(path, onData, onError = () => {}, quiet = false) {
  const cached = await cachedJSON(path);
  if (cached) onData(cached, true);
  if (!Key.get()) { if (!cached) onError(Object.assign(new Error("nokey"), { status: 0 })); return; }
  try {
    const fresh = await fetchJSON(path);
    if (!cached || fresh.generated_at !== cached.generated_at) onData(fresh, false);
  } catch (e) { if (!cached) onError(e); else if (!quiet) toast("最新データを読めませんでした（前回のデータを表示中）"); }
}
async function loadData(onData, onError) { return loadJSON(DATA_FILE, d => onData(prepare(d)), onError); }
// 市場の天気・チャート・ニュース（毎日更新）。まだ無ければ何もしない
let CHART = null, MARKET = null, NEWS = null, MOVERS = null, PICKS = null;
function loadChart(cb) { return loadJSON("data/chart.json", d => { CHART = d; cb && cb(d); }, () => {}, true); }
function loadMarket(cb) { return loadJSON("data/market.json", d => { MARKET = d; cb && cb(d); }, () => {}, true); }
function loadPicks(cb) { return loadJSON("data/picks.json", d => { PICKS = d; cb && cb(d); }, () => {}, true); }
function loadMovers(cb) { return loadJSON("data/movers.json", d => { MOVERS = d; cb && cb(d); }, () => {}, true); }
function loadNews(cb) { return loadJSON("data/news.json", d => { NEWS = d; cb && cb(d); }, () => {}, true); }
const TIMING_STYLE = { "買い場候補": "ok", "やや良い": "star", "様子見": "gray", "待ち・注意": "warn" };
function timingOf(code) { return CHART && CHART.stocks ? CHART.stocks[code] || null : null; }
// 終値の列から、小さな折れ線（SVG）を作る
function sparkSVG(vals, { w = 120, h = 36, color = "var(--sub)", fill = true, lines = [] } = {}) {
  const v = vals.filter(x => x !== null && x !== undefined);
  if (v.length < 2) return el("span");
  const all = v.concat(...lines.map(l => l.vals.filter(x => x != null)));
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const X = i => (i / (vals.length - 1)) * w, Y = x => h - 2 - ((x - lo) / span) * (h - 4);
  const pts = arr => arr.map((x, i) => x == null ? null : `${X(i).toFixed(1)},${Y(x).toFixed(1)}`).filter(Boolean).join(" ");
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`); svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true"); svg.style.width = "100%"; svg.style.height = h + "px"; svg.style.display = "block";
  const id = "g" + Math.random().toString(36).slice(2, 8);
  if (fill) {
    svg.innerHTML = `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".22"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`
      + `<polygon fill="url(#${id})" points="0,${h} ${pts(vals)} ${w},${h}"/>`;
  }
  for (const l of lines) svg.innerHTML += `<polyline fill="none" stroke="${l.color}" stroke-width="${l.width || 1.2}" ${l.dash ? `stroke-dasharray="${l.dash}"` : ""} points="${pts(l.vals)}"/>`;
  svg.innerHTML += `<polyline fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" points="${pts(vals)}"/>`;
  return svg;
}
function movingAvg(vals, n) { return vals.map((_, i) => i < n - 1 ? null : vals.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n); }

// ── 点数の計算（アプリ側で重みを変えて計算し直せる） ──
function currentStyle() { return store.get("invest-style", "balanced"); }
function setStyle(s) { store.set("invest-style", s); }
function weightsFor(data, style = currentStyle()) {
  if (style === "custom") { const w = store.get("invest-custom-weights", null); if (w) return w; }
  return data.styles[style] || data.styles.balanced;
}
function rankOf(score, ranks) { for (const [th, r] of ranks) if (score >= th) return r; return "D"; }
function totalOf(sub, adj, w) {
  let t = 0;
  for (const k of FACTOR_KEYS) t += (sub[k] || 0) * (w[k] || 0) / 100;
  return Math.max(0, Math.min(100, t + adj));
}
function prepare(data) {
  data.byCode = new Map(data.stocks.map(s => [s.c, s]));
  return data;
}
// 重みで全銘柄を採点し、点数順に並べる。前回の点数（同じ重み）と順位も付ける
function scoreAll(data, w) {
  for (const s of data.stocks) { s.score = totalOf(s.s, s.adj, w); s.rank = rankOf(s.score, data.ranks); }
  const list = [...data.stocks].sort((a, b) => b.score - a.score);
  list.forEach((s, i) => { s.pos = i + 1; });
  if (data.prev && data.prev.scores) {
    const prevList = Object.entries(data.prev.scores).map(([c, v]) => {
      const sub = {}; FACTOR_KEYS.forEach((k, i) => { sub[k] = v[i]; });
      return [c, totalOf(sub, v[6], w)];
    }).sort((a, b) => b[1] - a[1]);
    const prevPos = new Map(prevList.map(([c, sc], i) => [c, { pos: i + 1, score: sc }]));
    for (const s of list) {
      const p = prevPos.get(s.c);
      s.prevScore = p ? p.score : null; s.prevPos = p ? p.pos : null;
      s.prevRank = p ? rankOf(p.score, data.ranks) : null;
    }
  }
  return list;
}

// ── 見た目の部品 ──
function rankEl(r, size) {
  const e = el("span", { class: "rank " + r, text: r, "aria-label": r + "ランク" });
  if (size) Object.assign(e.style, { width: size + "px", height: size + "px", fontSize: Math.round(size * .52) + "px", borderRadius: Math.round(size * .34) + "px" });
  return e;
}
function deltaEl(s) {
  if (s.prevPos === undefined) return null;
  if (s.prevPos === null) return el("span", { class: "delta new", text: "NEW" });
  const d = s.prevPos - s.pos;
  if (Math.abs(d) < 1) return el("span", { class: "delta flat", text: "→" });
  return el("span", { class: "delta " + (d > 0 ? "up" : "down"), text: (d > 0 ? "▲" : "▼") + Math.abs(d) });
}
function fbarsEl(sub) {
  return el("div", { class: "fbars", "aria-hidden": "true" },
    FACTOR_KEYS.map(k => el("span", { class: "fbar " + k }, [el("i", { style: { width: Math.round(sub[k] || 0) + "%" } })])));
}
function legendEl() {
  return el("div", { class: "flegend", "aria-hidden": "true" }, FACTOR_KEYS.map(k => el("span", { text: FACTOR_SHORT[k] })));
}
const Watch = {
  all() { return store.get("invest-watch", []); },
  has(c) { return Watch.all().includes(c); },
  add(c) { const w = Watch.all(); if (!w.includes(c)) { w.unshift(c); store.set("invest-watch", w); } },
  toggle(c) {
    const w = Watch.all(); const i = w.indexOf(c);
    if (i >= 0) { w.splice(i, 1); Tags.clear(c); } else w.unshift(c);
    store.set("invest-watch", w); return i < 0;
  },
};
// タグ（要監視・買い候補など）。タグを付けるとウォッチにも入る。この端末に保存
const DEFAULT_TAGS = [
  { id: "watch", label: "👀 監視中", color: "var(--p-sky)" },
  { id: "buy", label: "🛒 買い候補", color: "var(--p-mint)" },
  { id: "hold", label: "💼 保有中", color: "var(--p-sun)" },
  { id: "wait", label: "💤 様子見", color: "var(--p-sand)" },
];
const TAG_COLORS = ["var(--p-peach)", "var(--p-lilac)", "var(--p-pink)", "var(--p-sky)", "var(--p-mint)", "var(--p-sun)"];
const Tags = {
  defs() { return store.get("invest-tagdefs", DEFAULT_TAGS); },
  addDef(label) {
    const defs = Tags.defs(); const id = "t" + Date.now().toString(36);
    defs.push({ id, label, color: TAG_COLORS[defs.length % TAG_COLORS.length] }); store.set("invest-tagdefs", defs); return id;
  },
  removeDef(id) {
    store.set("invest-tagdefs", Tags.defs().filter(d => d.id !== id));
    const m = Tags.map(); for (const c in m) m[c] = m[c].filter(t => t !== id); store.set("invest-tags", m);
  },
  map() { return store.get("invest-tags", {}); },
  of(c) { return Tags.map()[c] || []; },
  toggle(c, id) {
    const m = Tags.map(); const cur = m[c] || []; const i = cur.indexOf(id);
    if (i >= 0) cur.splice(i, 1); else { cur.push(id); Watch.add(c); }
    m[c] = cur; store.set("invest-tags", m); return i < 0;
  },
  clear(c) { const m = Tags.map(); delete m[c]; store.set("invest-tags", m); },
  def(id) { return Tags.defs().find(d => d.id === id); },
};
function tagChip(id) {
  const d = Tags.def(id); if (!d) return null;
  return el("span", { class: "badge", style: { background: d.color }, text: d.label });
}
function stockRow(s, { showPos = true } = {}) {
  const metas = [["ROE", fmt.pct(s.roe)], ["予想PER", s.fper ? s.fper.toFixed(2) + "倍" : "–"], ["利回り", fmt.pct(s.dy)], ["ROE−DOE", fmt.pct(s.rd)]];
  return el("a", { class: "stock", href: `stock.html?c=${encodeURIComponent(s.c)}` }, [
    el("div", { class: "head" }, [
      showPos ? el("span", { class: "pos", text: s.pos }) : null,
      el("span", { class: "rk", title: "会社の良さのランク（S〜D）。チャートや勢いは含まない" }, [rankEl(s.rank), el("small", { text: "会社の質" })]),
      el("span", { class: "nm" }, [el("b", { text: s.n || s.c }),
        el("small", { text: [s.c, s.m, Watch.has(s.c) ? "★ウォッチ中" : ""].filter(Boolean).join("　") })]),
      el("span", { class: "pt", title: "会社の良さの点数（100点満点）" }, [el("span", { class: "score", text: Math.round(s.score) }), el("small", { class: "unit", text: "点/100" }), deltaEl(s)]),
    ]),
    fbarsEl(s.s),
    el("div", { class: "meta" }, metas.map(([k, v]) => el("span", {}, [k + " ", el("b", { text: v })]))),
    (s.b.length || s.f.length || Tags.of(s.c).length || timingOf(s.c)) ? el("div", { class: "tags" }, [
      timingOf(s.c) ? el("span", { class: "badge " + (TIMING_STYLE[timingOf(s.c).label] || "gray"), text: "📈 " + timingOf(s.c).label }) : null,
      ...Tags.of(s.c).map(tagChip),
      ...s.b.map(b => el("span", { class: "badge star", text: "★ " + b })),
      ...s.f.map(f => el("span", { class: "badge warn", text: "⚠ " + f })),
    ]) : null,
  ]);
}
function skeleton(n = 5) { return Array.from({ length: n }, () => el("div", { class: "skel" })); }

// 合い鍵がない・使えないときの案内
function keyNeeded(container, e) {
  container.replaceChildren(el("div", { class: "card rise" }, [
    el("div", { class: "empty", html: e && e.status === 0
      ? "はじめまして🐤<br>採点の結果は非公開の場所にあるので、<br>最初に「合い鍵」をこの端末に登録してね。"
      : "データを読めませんでした🐤<br>" + (e ? e.message : "") }),
    el("div", { class: "actions" }, [el("a", { class: "btn primary", href: "key.html", text: "🔑 合い鍵を登録する" })]),
  ]));
}

// ── 採点を今すぐ動かす ──
async function dispatchScore(style, plan) {
  return gh(`/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST", body: { ref: "main", inputs: { style, plan, top_n: "30" } } });
}
async function lastRun() {
  const r = await gh(`/repos/${REPO}/actions/workflows/${WORKFLOW}/runs?per_page=1`);
  return r.workflow_runs[0] || null;
}

// ── 下から出るシート ──
function openSheet(content) {
  let bg = $("sheet-bg"), sh = $("sheet");
  if (!bg) {
    bg = el("div", { id: "sheet-bg", class: "sheet-bg", onclick: closeSheet });
    sh = el("div", { id: "sheet", class: "sheet", role: "dialog", "aria-modal": "true" });
    document.body.append(bg, sh);
  }
  sh.replaceChildren(...[].concat(content));
  requestAnimationFrame(() => { bg.classList.add("open"); sh.classList.add("open"); });
}
function closeSheet() { $("sheet-bg")?.classList.remove("open"); $("sheet")?.classList.remove("open"); }

// ── 下のナビ ──
(function dock() {
  if (document.body.dataset.nodock !== undefined) return;
  const here = location.pathname.split("/").pop() || "index.html";
  const items = [["index.html", "🏠", "ホーム"], ["market.html", "🌤️", "市場"], ["ranking.html", "🏅", "ランキング"],
                 ["screen.html", "🔍", "さがす"], ["watch.html", "⭐", "ウォッチ"]];
  document.body.append(el("nav", { class: "dock", "aria-label": "メニュー" }, items.map(([href, icon, label]) =>
    el("a", { href: href === "index.html" ? "./" : href, "aria-current": here === href ? "page" : null }, [el("span", { class: "i", text: icon }), label]))));
})();

// ── AI分析 ──
const AI = {
  gemini: { name: "Gemini", cost: "無料枠で使える", icon: "✨" },
  claude: { name: "Claude", cost: "1回 20〜30円の目安", icon: "🧠" },
};
async function fetchAnalysis(code) {
  try { return JSON.parse(await gh(`/repos/${REPO}/contents/analysis/${encodeURIComponent(code)}.json?ref=main`, { accept: "application/vnd.github.raw+json" })); }
  catch (e) { if (e.status === 404) return null; throw e; }
}
// 分析を動かし、終わるまで待つ。onTick(経過秒) で進み具合を知らせる。成功なら true
async function runAnalysis(code, model, onTick) {
  const started = new Date(Date.now() - 10000).toISOString();
  await gh(`/repos/${REPO}/actions/workflows/analyze.yml/dispatches`, { method: "POST", body: { ref: "main", inputs: { code, model } } });
  const t0 = Date.now();
  while (Date.now() - t0 < 6 * 60000) {
    await new Promise(r => setTimeout(r, 6000));
    onTick && onTick(Math.round((Date.now() - t0) / 1000));
    try {
      const runs = await gh(`/repos/${REPO}/actions/workflows/analyze.yml/runs?event=workflow_dispatch&per_page=5`);
      const run = runs.workflow_runs.find(r => r.created_at >= started.slice(0, 19));
      if (run && run.status === "completed") return { ok: run.conclusion === "success", url: run.html_url };
    } catch (e) { /* 次の回でもう一度見る */ }
  }
  return { ok: false, timeout: true };
}
// AIが書いたMarkdownを安全に表示する（見出し・箇条書き・太字・リンクだけ）
function mdToEls(md) {
  const esc = s => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const out = []; let list = null;
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    const li = line.match(/^\s*(?:[-*・]|\d+\.)\s+(.*)$/);
    if (li) { if (!list) { list = el("ul"); out.push(list); } list.append(el("li", { html: inline(li[1]) })); continue; }
    list = null;
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { out.push(el("hr", { style: { border: 0, borderTop: "1px dashed var(--line)", margin: "12px 0" } })); continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) out.push(el(h[1].length <= 2 ? "h4" : "h5", { html: inline(h[2]) }));
    else if (line.trim()) out.push(el("p", { html: inline(line) }));
  }
  return out;
}

// 説明文は「？ この画面の使い方」を押したときだけ開く
(function foldHelp() {
  for (const p of document.querySelectorAll("p.note")) {
    if (p.dataset.keep !== undefined) continue;
    const d = el("details", { class: "help" }, [el("summary", { text: "？ この画面の使い方" })]);
    p.replaceWith(d); d.append(p);
  }
})();

// ホーム画面に追加したときに速く開くため（画面のファイルだけを端末に残す）
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

// 売買ライン（買う値段・利確・損切り）
function planEl(pl, compact) {
  if (!pl) return "";
  const y = v => Math.round(v).toLocaleString() + "円", pc = v => (v > 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
  if (compact) return el("div", { class: "plan-c" }, [
    el("span", {}, ["買い ", el("b", { text: y(pl.entry) })]),
    el("span", { class: "up" }, ["利確 ", el("b", { text: y(pl.tp1) }), ` (${pc(pl.tp1_pct)})`]),
    el("span", { class: "down" }, ["損切り ", el("b", { text: y(pl.stop) }), ` (${pc(pl.stop_pct)})`])]);
  return el("div", { class: "plan-l" }, [
    el("div", { class: "ladder" }, [
      el("div", { class: "up" }, [el("span", { text: "🎯 利確2" }), el("b", { text: y(pl.tp2) }), el("small", { text: pc(pl.tp2_pct) })]),
      el("div", { class: "up" }, [el("span", { text: "🎯 利確1" }), el("b", { text: y(pl.tp1) }), el("small", { text: pc(pl.tp1_pct) })]),
      el("div", { class: "in" }, [el("span", { text: "🛒 買い" }), el("b", { text: y(pl.entry) }), el("small", { text: "目安" })]),
      el("div", { class: "down" }, [el("span", { text: "🛑 損切り" }), el("b", { text: y(pl.stop) }), el("small", { text: pc(pl.stop_pct) })])]),
    el("div", { class: "exh", text: "🛒 買うタイミング" }), el("ul", {}, pl.entry_how.map(t => el("li", { text: t }))),
    el("div", { class: "exh", text: "🛑 損切りの根拠" }), el("p", { class: "plan", text: pl.stop_why }),
    el("div", { class: "exh", text: "📏 ルール" }), el("ul", {}, pl.rules.map(t => el("li", { text: t })))]);
}

// いまの株価（約20分遅れ）: ボタンでGitHubに取りに行ってもらい、終わったら読み込む
let QUOTES = null;
function loadQuotes(cb) { return loadJSON("data/quotes.json", d => { QUOTES = d; cb && cb(d); }, () => {}, true); }
async function refreshQuotes(onStep) {
  const t0 = Date.now();
  await gh(`/repos/${REPO}/actions/workflows/quote.yml/dispatches`, { method: "POST", body: { ref: "main", inputs: { codes: Watch.all().slice(0, 30).join(",") } } });
  onStep && onStep("株価を取りに行っています…");
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, i < 3 ? 8000 : 5000));
    try {
      const r = await gh(`/repos/${REPO}/actions/workflows/quote.yml/runs?per_page=1`);
      const run = r.workflow_runs[0];
      if (run && Date.parse(run.created_at) >= t0 - 60000 && run.status === "completed") {
        if (run.conclusion !== "success") throw new Error("株価を取得できませんでした");
        QUOTES = await fetchJSON("data/quotes.json");
        return QUOTES;
      }
      onStep && onStep(`株価を取りに行っています…（${Math.round((Date.now() - t0) / 1000)}秒）`);
    } catch (e) { if (e.message.includes("取得できません")) throw e; }
  }
  throw new Error("時間がかかっています。少ししてから開き直してください");
}
// いまの株価と売買ラインの位置関係
function liveEl(code, plan) {
  const q = QUOTES && QUOTES.quotes && QUOTES.quotes[code];
  if (!q) return "";
  const y = v => Math.round(v).toLocaleString() + "円";
  let st = "", cls = "";
  if (plan) {
    if (q.p <= plan.stop) { st = "🛑 損切りラインを下回っています"; cls = "down"; }
    else if (q.p >= plan.tp2) { st = "🎯 利確2に届いています"; cls = "up"; }
    else if (q.p >= plan.tp1) { st = "🎯 利確1に届いています"; cls = "up"; }
    else if (Math.abs(q.p / plan.entry - 1) <= 0.01) { st = "🛒 買いの目安の近く（±1%）"; cls = "in"; }
    else st = q.p > plan.entry ? `買いの目安より ${((q.p / plan.entry - 1) * 100).toFixed(2)}% 上` : `買いの目安より ${((q.p / plan.entry - 1) * 100).toFixed(2)}% 下`;
  }
  return el("div", { class: "live " + cls }, [
    el("span", {}, ["今 ", el("b", { text: y(q.p) }), q.chg == null ? "" : el("span", { class: q.chg > 0 ? "up" : q.chg < 0 ? "down" : "", text: ` ${q.chg > 0 ? "+" : ""}${(q.chg * 100).toFixed(2)}%` }), el("small", { text: ` ${q.time}` })]),
    st ? el("span", { class: "st", text: st }) : ""]);
}
