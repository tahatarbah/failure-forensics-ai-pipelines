import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Failure Forensics",
  description: "Failure forensics for AI pipelines — LLM, agents, and MLOps",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=JetBrains+Mono:wght@400;500&family=Sora:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <div className="app-shell">
          <header className="topbar">
            <a href="/" className="brand-block">
              <div className="brand-mark" aria-hidden />
              <div>
                <div className="brand">
                  Failure <em>Forensics</em>
                </div>
                <div className="brand-sub">AI pipeline root-cause analysis</div>
              </div>
            </a>
            <div className="top-meta">
              <span className="status-pip" aria-hidden />
              <span>LOCAL WORKBENCH</span>
              <a className="btn btn-ghost btn-sm" href="/">
                Cases
              </a>
            </div>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
