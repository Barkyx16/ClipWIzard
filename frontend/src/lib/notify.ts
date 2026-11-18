/** Desktop notifications for long jobs. Only shown while the tab is in the background. */

export function canNotify(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** Ask once, from a user gesture (starting an upload). */
export function askNotifyPermission(): void {
  if (canNotify() && Notification.permission === "default") {
    Notification.requestPermission().catch(() => undefined);
  }
}

export function notify(title: string, body: string, url?: string): void {
  if (!canNotify() || Notification.permission !== "granted" || !document.hidden) return;
  try {
    const n = new Notification(title, { body, icon: "/favicon.svg", tag: url ?? title });
    n.onclick = () => {
      window.focus();
      if (url && window.location.pathname !== url) window.location.href = url;
      n.close();
    };
  } catch {
    /* some mobile browsers only allow notifications from a service worker */
  }
}
