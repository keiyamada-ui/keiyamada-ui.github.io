// ことり投資ノート: 画面のファイルを端末に残して、ホーム画面から速く開けるようにする
// 画面はいつも最新を取りに行き、通信できないときだけ残したものを使う（データは app.js が別に管理）
const SHELL = "invest-shell-v13";
const FILES = ["./", "index.html", "market.html", "picks.html", "ranking.html", "stock.html", "watch.html", "screen.html", "tune.html", "plan.html", "more.html", "key.html",
               "app.css", "app.js", "header.jpg", "avatar.png", "icon-192.png"];

self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES)).catch(() => {})); self.skipWaiting(); });
self.addEventListener("activate", e => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith("invest-shell-") && k !== SHELL) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;  // GitHub API などには触らない
  e.respondWith((async () => {
    try {
      const res = await fetch(e.request);
      if (res.ok) (await caches.open(SHELL)).put(e.request, res.clone());
      return res;
    } catch (err) {
      return (await caches.match(e.request, { ignoreSearch: true })) || Response.error();
    }
  })());
});
