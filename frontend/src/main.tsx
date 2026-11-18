import "@fontsource-variable/inter";
import "@fontsource/bebas-neue";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import ProjectPage from "./pages/ProjectPage";
import SharePage from "./pages/SharePage";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="/videos/:id" element={<ProjectPage />} />
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
