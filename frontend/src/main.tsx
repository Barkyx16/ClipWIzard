import "@fontsource-variable/inter";
import "@fontsource/bebas-neue";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import LibraryPage from "./pages/LibraryPage";
import ProjectPage from "./pages/ProjectPage";
import SharePage from "./pages/SharePage";

const root = createRoot(document.getElementById("root")!);
const render = () =>
  root.render(
    <StrictMode>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="/videos/:id" element={<ProjectPage />} />
            <Route path="/clips" element={<LibraryPage />} />
            <Route
              path="*"
              element={
                <div className="card mx-auto max-w-lg p-8 text-center">
                  <p className="font-display text-5xl tracking-wide">Wasted</p>
                  <p className="mt-2 text-muted">That page doesn't exist.</p>
                  <a href="/" className="btn-ghost mt-5">
                    Back to ClipWizard
                  </a>
                </div>
              }
            />
          </Route>
          <Route path="/s/:token" element={<SharePage />} />
        </Routes>
      </BrowserRouter>
    </StrictMode>,
  );

// Make sure this browser has its workspace cookie *before* the app fires several
// API calls in parallel (each would otherwise mint a different workspace).
// Shared clip pages are public and don't need one.
const linkedKey = window.location.hash.match(/^#ws=([A-Za-z0-9_-]{32,64})$/)?.[1];
if (window.location.pathname.startsWith("/s/")) render();
else if (linkedKey) {
  // Opened from "open on another device": adopt that workspace, then hide the key.
  history.replaceState(null, "", window.location.pathname + window.location.search);
  fetch("/api/workspace", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key: linkedKey }),
  })
    .catch(() => undefined)
    .finally(render);
} else
  fetch("/api/workspace", { credentials: "same-origin" })
    .catch(() => undefined)
    .finally(render);
