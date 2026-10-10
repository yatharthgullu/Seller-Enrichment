import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";
const systemTheme = (): Theme => (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

function initial(): Theme {
  const q = window.location.hash.split("?")[1];
  const fromUrl = q ? new URLSearchParams(q).get("theme") : null;
  if (fromUrl === "light" || fromUrl === "dark") return fromUrl;
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage can be blocked; fall back to the system setting */
  }
  return systemTheme();
}

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      onClick={() => {
        setTheme(next);
        try { localStorage.setItem("theme", next); } catch { /* ignore */ }
      }}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className={"grid h-9 w-9 place-items-center rounded-lg border border-line text-ink-2 transition hover:bg-mute-soft hover:text-ink " + (className ?? "")}
    >
      {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
}
