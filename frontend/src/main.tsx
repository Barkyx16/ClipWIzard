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
if (window.location.pathname.startsWith("/s/")) render();
else
  fetch("/api/workspace", { credentials: "same-origin" })
    .catch(() => undefined)
    .finally(render);
