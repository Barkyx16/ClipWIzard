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
        </Route>
        <Route path="/s/:token" element={<SharePage />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
