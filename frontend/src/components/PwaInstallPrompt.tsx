import { useEffect, useState } from "react";

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export function PwaInstallPrompt() {
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    const onBeforeInstall = (event: Event) => {
      event.preventDefault();
      setInstallEvent(event as InstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setInstallEvent(null);
    };
    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const userAgent = navigator.userAgent;
  const isIos = /iPad|iPhone|iPod/.test(userAgent) && !("MSStream" in window);
  const isAndroid = /Android/.test(userAgent);
  const isMobile = isIos || isAndroid;
  if (installed || dismissed || window.matchMedia("(display-mode: standalone)").matches || (!installEvent && !isMobile)) return null;

  const install = async () => {
    if (!installEvent) {
      setHelpOpen(true);
      return;
    }
    await installEvent.prompt();
    const choice = await installEvent.userChoice;
    if (choice.outcome === "accepted") setInstallEvent(null);
  };

  return <>
    <div className="pwa-install-prompt" role="status"><div><strong>Install Passport Staff</strong><span>Keep booking and operations one tap away.</span></div><div className="toolbar"><button className="button small" onClick={() => void install}>{installEvent ? "Install" : "How to install"}</button><button className="button ghost small" onClick={() => setDismissed(true)}>Not now</button></div></div>
    {helpOpen && <div className="pwa-install-help" role="dialog" aria-modal="true" aria-label="Install Passport Staff"><div className="pwa-install-help-card"><div className="section-heading"><div><h2>Install Passport Staff</h2><p>Use your browser’s install option to add Passport to your home screen.</p></div><button className="icon-button" onClick={() => setHelpOpen(false)} aria-label="Close installation instructions">×</button></div>{isIos ? <ol><li>Tap the <strong>Share</strong> button in Safari.</li><li>Choose <strong>Add to Home Screen</strong>.</li><li>Tap <strong>Add</strong>, then open Passport from the new icon.</li></ol> : <ol><li>Open the browser menu.</li><li>Choose <strong>Install app</strong> or <strong>Add to Home screen</strong>.</li><li>Confirm the installation.</li></ol>}<button className="button" onClick={() => setHelpOpen(false)}>Close</button></div></div>}
  </>;
}
