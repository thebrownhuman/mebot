import React from "react";
import ReactDOM from "react-dom/client";
import EmbedApp, { parseLocation } from "./EmbedApp";
import "./embed.css";

const { slug, mode } = parseLocation(window.location);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <EmbedApp slug={slug} mode={mode} />
  </React.StrictMode>,
);
