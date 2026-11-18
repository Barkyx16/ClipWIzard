import { useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { KeyRound, Sparkles } from "lucide-react";

import WorkspaceDialog from "./WorkspaceDialog";

export default function Layout() {
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line/70 bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5" aria-label="ClipWizard home">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <span className="font-display text-3xl leading-none tracking-wide">
              Clip<span className="text-gradient">Wizard</span>
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden items-center gap-1.5 rounded-full border border-line px-3 py-1 text-xs text-muted md:inline-flex">
              <Sparkles className="h-3.5 w-3.5 text-accent" /> AI clipping for GTA 6 creators
            </span>
            <button type="button" className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setWorkspaceOpen(true)}>
              <KeyRound className="h-4 w-4" /> Workspace
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        <Outlet />
      </main>
      <footer className="border-t border-line/70 py-6 text-center text-xs text-dim">
        ClipWizard is a fan-made tool. Not affiliated with or endorsed by Rockstar Games or Take-Two
        Interactive. Grand Theft Auto is a trademark of its respective owner.
      </footer>
      <WorkspaceDialog open={workspaceOpen} onClose={() => setWorkspaceOpen(false)} />
    </div>
  );
}
