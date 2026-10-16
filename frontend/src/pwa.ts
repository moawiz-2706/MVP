export function registerPwaServiceWorker() {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch((error: unknown) => {
      console.warn("Passport PWA service worker registration failed", error);
    });
  }, { once: true });
}
