// ことり 管理画面の共通処理
// - データは GitHub の公開ファイル（raw）と GitHub API から読む
// - 入力・操作には「合い鍵」（GitHub の fine-grained トークン）が必要。この端末の中だけに保存する
const REPO = "keiyamada-ui/keiyamada-ui.github.io";
const OWNER = REPO.split("/")[0];
const RAW = "https://raw.githubusercontent.com/" + REPO + "/main/";
const API = "https://api.github.com";
const KEY_NAME = "kotori-gh-key";

const Key = {
  get() { try { return localStorage.getItem(KEY_NAME) || ""; } catch (e) { return ""; } },
  set(v) { try { localStorage.setItem(KEY_NAME, v); } catch (e) {} },
  clear() { try { localStorage.removeItem(KEY_NAME); } catch (e) {} },
};

function el(tag, attrs = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c !== null && c !== undefined && c !== false) n.append(c);
  return n;
}

function toast(msg) {
  let t = document.getElementById("toast");
  if (!t) { t = el("div", { id: "toast" }); document.body.append(t); }
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
  }
  toast("コピーしました");
}

// 公開ファイル（JSON）を読む。なければ null
async function raw(path) {
  try {
    const r = await fetch(RAW + path + "?t=" + Date.now());
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
}
async function rawText(path) {
  try {
    const r = await fetch(RAW + path + "?t=" + Date.now());
    return r.ok ? await r.text() : "";
  } catch (e) { return ""; }
}

// 最新のファイルを読む。合い鍵があれば GitHub API から直接読む（公開ファイルの配信は数分遅れることがあるため）
async function fresh(path) {
  if (!Key.get()) return raw(path);
  try {
    const r = await fetch(`${API}/repos/${REPO}/contents/${path}?ref=main&t=${Date.now()}`,
      { headers: { Accept: "application/vnd.github.raw+json", Authorization: "Bearer " + Key.get() } });
    if (r.status === 404) return null;
    return r.ok ? await r.json() : raw(path);
  } catch (e) { return raw(path); }
}

// ワークフローを今すぐ動かす（合い鍵が必要）
async function dispatch(file, inputs) {
  return gh(`/repos/${REPO}/actions/workflows/${file}/dispatches`, { method: "POST", body: { ref: "main", inputs } });
}

// GitHub API。合い鍵があれば付ける（なくても公開情報は読める）
async function gh(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/vnd.github+json" };
  const key = Key.get();
  if (key) headers.Authorization = "Bearer " + key;
  if (body) headers["Content-Type"] = "application/json";
  let r = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (key) {
    // 合い鍵の期限（GitHub が教えてくれる場合）と、使えなくなっていないかを覚えておく
    const exp = r.headers.get("github-authentication-token-expiration");
    try {
      if (exp) localStorage.setItem("kotori-key-exp", exp);
      if (r.status === 401) localStorage.setItem("kotori-key-bad", "1");
      else if (r.ok) localStorage.removeItem("kotori-key-bad");
    } catch (e) {}
    // 合い鍵が使えなくても、見るだけの情報は合い鍵なしで読めるようにする
    if (r.status === 401 && method === "GET") {
      delete headers.Authorization;
      r = await fetch(API + path, { method, headers });
    }
  }
  if (!r.ok) {
    let msg = "";
    try { msg = (await r.json()).message || ""; } catch (e) {}
    const err = new Error(explain(r.status, msg));
    err.status = r.status;
    throw err;
  }
  return r.status === 204 ? null : r.json();
}

function explain(status, msg) {
  if (status === 401) return "合い鍵が使えなくなっています（期限切れ・作り直し・削除など）。「🔑 合い鍵の設定」で登録し直してください";
  if (status === 403 && /rate limit/i.test(msg)) return "読み込みの回数制限に達しました。少し待つか、合い鍵を登録すると増えます";
  if (status === 403 || status === 404) return "権限が足りません。合い鍵の権限（Issues・Actions の Read and write）を確認してください";
  return `うまくいきませんでした（${status} ${msg}）`;
}

// 合い鍵の状態: "none"（未登録）・"bad"（使えない）・"soon"（期限が14日以内）・"ok"。days は期限までの日数
function keyHealth() {
  if (!Key.get()) return { state: "none" };
  let bad = false, exp = "";
  try { bad = localStorage.getItem("kotori-key-bad") === "1"; exp = localStorage.getItem("kotori-key-exp") || ""; } catch (e) {}
  const t = exp ? Date.parse(exp.replace(" UTC", "Z").replace(" ", "T")) : NaN;
  const days = isNaN(t) ? null : Math.floor((t - Date.now()) / 86400000);
  if (bad) return { state: "bad", days };
  if (days !== null && days <= 14) return { state: "soon", days, exp: new Date(t) };
  return { state: "ok", days, exp: isNaN(t) ? null : new Date(t) };
}

function needKeyBox() {
  return el("div", { class: "info" }, [
    "この操作には「合い鍵」が必要です（最初に1回だけ）。",
    el("br"), el("a", { href: "key.html", text: "🔑 合い鍵を登録する →" }),
  ]);
}

// 日本時間の日付（YYYY-MM-DD）。offset は日数
function jstDate(offset = 0) {
  const d = new Date(Date.now() + 9 * 3600000 + offset * 86400000);
  return d.toISOString().slice(0, 10);
}
function addDays(day, n) {
  const d = new Date(day + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function jstTime(iso) {
  if (!iso) return "";
  const d = new Date(new Date(iso).getTime() + 9 * 3600000);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}
function weekday(day) { return "日月火水木金土"[new Date(day + "T00:00:00Z").getUTCDay()]; }

// タブ: [[ボタンのid, 名前], ...]。URL の #名前 で最初のタブを選べる
function setupTabs(tabs, onChange) {
  const pick = name => {
    for (const [id, n] of tabs) document.getElementById(id).setAttribute("aria-selected", String(n === name));
    history.replaceState(null, "", "#" + name);
    onChange(name);
  };
  for (const [id, name] of tabs) document.getElementById(id).addEventListener("click", () => pick(name));
  const start = location.hash.slice(1);
  pick(tabs.some(([, n]) => n === start) ? start : tabs[0][1]);
}

// 「前に見た時刻」（ホーム画面の赤いバッジ用。この端末だけ）
const Seen = {
  get() { try { return JSON.parse(localStorage.getItem("kotori-seen") || "{}"); } catch (e) { return {}; } },
  mark(name) {
    const v = Seen.get();
    v[name] = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 16) + "+09:00";  // 投稿記録と同じ日本時間の書き方
    try { localStorage.setItem("kotori-seen", JSON.stringify(v)); } catch (e) {}
  },
};

const KIND = { buzz: "📣 集客投稿", casual: "💬 つぶやき", value: "📘 役立つ投稿", pr: "🛒 PR 投稿" };

// ── 通知とアプリのアイコンの赤いバッジ ──
// 通知を受け取る係（sw.js）を登録する。ホーム画面に追加したアプリで、通知を許可すると使える
const SW = ("serviceWorker" in navigator) ? navigator.serviceWorker.register("sw.js").catch(() => null) : Promise.resolve(null);

function isHomeApp() {
  return navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
}

// アイコンの数字を、管理画面で数えた「まだ見ていないもの」の数に合わせる
async function syncAppBadge(n) {
  try { if (n > 0) await navigator.setAppBadge(n); else await navigator.clearAppBadge(); } catch (e) {}
  try { const reg = await SW; if (reg && reg.active) reg.active.postMessage({ type: "badge", count: n }); } catch (e) {}
}

function pushState() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return isHomeApp() ? "unsupported" : "need-home";
  }
  return Notification.permission === "granted" ? "granted" : Notification.permission === "denied" ? "denied" : "default";
}

// 「通知をオンにする」。許可を求め、この端末を登録するワークフローを動かす
async function enablePush(onProgress) {
  const permission = await Notification.requestPermission();  // ボタンを押した直後に呼ぶ必要がある
  if (permission !== "granted") throw new Error("通知が許可されませんでした。iPhone の「設定 → 通知 → ことり」で許可できます");
  onProgress("準備しています…");
  let pub = await fresh("_affiliate/data/push/public.json");
  if (!pub) {
    await dispatch("affiliate_push.yml", { mode: "setup" });
    for (let i = 0; i < 30 && !pub; i++) {
      await new Promise(r => setTimeout(r, 6000));
      pub = await fresh("_affiliate/data/push/public.json");
    }
    if (!pub) throw new Error("準備に時間がかかっています。GitHub Secrets に KOTORI_STORE_KEY が登録されているか確認してください");
  }
  const reg = await navigator.serviceWorker.ready;
  const raw64 = pub.key.replace(/-/g, "+").replace(/_/g, "/");
  const key = Uint8Array.from(atob(raw64 + "=".repeat((4 - raw64.length % 4) % 4)), c => c.charCodeAt(0));
  const sub = (await reg.pushManager.getSubscription()) ||
              (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }));
  onProgress("この端末を登録しています…（1〜2分）");
  await dispatch("affiliate_push.yml", { mode: "subscribe", subscription: JSON.stringify(sub) });
  try { localStorage.setItem("kotori-push", "on"); } catch (e) {}
}

// ワークフローを動かして、終わるまで待つ。返り値: 成功したら true
async function runAndWait(file, inputs, onProgress, maxMinutes = 6) {
  const started = new Date(Date.now() - 5000).toISOString().slice(0, 19);
  await dispatch(file, inputs);
  for (let i = 0; i < maxMinutes * 60 / 8; i++) {
    await new Promise(r => setTimeout(r, 8000));
    if (onProgress) onProgress(i);
    try {
      const runs = await gh(`/repos/${REPO}/actions/workflows/${file}/runs?event=workflow_dispatch&per_page=3`);
      const run = runs.workflow_runs.find(r => r.created_at >= started);
      if (run && run.status === "completed") return run.conclusion === "success";
    } catch (e) { /* 次の回でもう一度見る */ }
  }
  throw new Error("時間がかかっています。少ししてからページを開き直してください");
}

// 最新のファイルを文字のまま読む（合い鍵があれば GitHub API から）
async function freshText(path) {
  if (!Key.get()) return rawText(path);
  try {
    const r = await fetch(`${API}/repos/${REPO}/contents/${path}?ref=main&t=${Date.now()}`,
      { headers: { Accept: "application/vnd.github.raw+json", Authorization: "Bearer " + Key.get() } });
    return r.ok ? await r.text() : "";
  } catch (e) { return ""; }
}

// ── 下のナビ（どの画面にも同じものを出す） ──
(function dock() {
  if (document.querySelector("nav.dock") || document.body.dataset.nodock !== undefined) return;
  const here = location.pathname.split("/").pop() || "index.html";
  const items = [["index.html", "🏠", "ホーム"], ["posts.html", "📣", "投稿"], ["comments.html", "💬", "コメント"],
                 ["pins.html", "📌", "ピン"], ["stats.html", "📊", "成果"]];
  const nav = el("nav", { class: "dock", "aria-label": "よく使う画面" },
    items.map(([href, icon, label]) => el("a", { href: href === "index.html" ? "./" : href, "aria-current": here === href ? "page" : null },
      [el("span", { class: "i", text: icon }), label, el("span", { class: "dot", id: "dock-" + href.split(".")[0] })])));
  document.body.append(nav);
})();
