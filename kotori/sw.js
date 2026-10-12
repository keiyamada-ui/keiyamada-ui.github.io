// ことり 管理画面: 通知を受け取って表示し、アプリのアイコンに赤いバッジ（数字）を付ける
const BADGE = "kotori-badge";

async function getCount() {
  try { const r = await (await caches.open(BADGE)).match("count"); return r ? +(await r.text()) || 0 : 0; } catch (e) { return 0; }
}
async function setCount(n) {
  try { await (await caches.open(BADGE)).put("count", new Response(String(n))); } catch (e) {}
  try { if (n > 0) await self.navigator.setAppBadge(n); else await self.navigator.clearAppBadge(); } catch (e) {}
}

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data.json(); } catch (err) { d = { title: "ことり", body: e.data ? e.data.text() : "" }; }
  e.waitUntil((async () => {
    await setCount((await getCount()) + (d.add ?? 1));
    await self.registration.showNotification(d.title || "ことり", {
      body: d.body || "", icon: "icon-192.png", badge: "icon-192.png", data: { url: d.url || "./" } });
  })());
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL(e.notification.data.url || "./", self.registration.scope).href;
  e.waitUntil((async () => {
    for (const c of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {
      if ("focus" in c) { await c.navigate(url).catch(() => {}); return c.focus(); }
    }
    return self.clients.openWindow(url);
  })());
});

// 管理画面を開いたときに、実際の数に合わせる
self.addEventListener("message", e => { if (e.data && e.data.type === "badge") e.waitUntil(setCount(e.data.count)); });
