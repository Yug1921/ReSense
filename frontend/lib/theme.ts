// Light or dark look, picked with the header toggle. Saved in this browser;
// with nothing saved it follows the device setting. The inline script in
// app/layout.tsx applies it before the first paint so the page never flashes.
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "resense-theme";
const EVENT = "resense-theme-change";

export function getTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function setTheme(theme: Theme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // not saved, but still applied to this page
  }
  const apply = () => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
    window.dispatchEvent(new CustomEvent(EVENT, { detail: theme }));
  };
  // Cross-fade the whole page where the browser supports it; otherwise the
  // `theme-fading` class eases each colour change.
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced && "startViewTransition" in document) {
    (document as Document & { startViewTransition: (cb: () => void) => unknown }).startViewTransition(apply);
    return;
  }
  const root = document.documentElement;
  root.classList.add("theme-fading");
  apply();
  window.setTimeout(() => root.classList.remove("theme-fading"), 450);
}

export function onThemeChange(listener: () => void) {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

// Runs in <head> before React: pick the saved theme, else the device's.
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t!=="light"&&t!=="dark"){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}var r=document.documentElement;r.dataset.theme=t;r.classList.toggle("dark",t==="dark");r.style.colorScheme=t}catch(e){}})();`;
