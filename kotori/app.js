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
  const r = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
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
  if (status === 401) return "合い鍵が無効です（期限切れ・入力ミス）。「🔑 合い鍵の設定」で登録し直してください";
  if (status === 403 && /rate limit/i.test(msg)) return "読み込みの回数制限に達しました。少し待つか、合い鍵を登録すると増えます";
  if (status === 403 || status === 404) return "権限が足りません。合い鍵の権限（Issues・Actions の Read and write）を確認してください";
  return `うまくいきませんでした（${status} ${msg}）`;
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

const KIND = { buzz: "📣 集客投稿", casual: "💬 つぶやき", value: "📘 役立つ投稿", pr: "🛒 PR 投稿" };
