export function standalonePwaUrl(): string {
  const configured = String(import.meta.env.VITE_PWA_APP_URL || "").trim();
  const base = configured || window.location.origin;
  return `${base.replace(/\/+$/, "")}/app`;
}

export function isEmbeddedInHighLevel(): boolean {
  return window.parent !== window;
}

export function registerPwaServiceWorker() {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch((error: unknown) => {
      console.warn("Passport PWA service worker registration failed", error);
    });
  }, { once: true });
}
