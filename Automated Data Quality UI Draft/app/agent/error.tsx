"use client";

import { useEffect } from "react";
import styles from "../workflow.module.css";

export default function AskAiError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error("[ask-ai] client render failed", error);
  }, [error]);

  return (
    <main className={styles.appShell}>
      <section className={styles.panel} role="alert" aria-labelledby="ask-ai-error-title">
        <span className={styles.eyebrow}>ASK AI / RECOVERY</span>
        <h1 id="ask-ai-error-title">Ask AI could not load</h1>
        <p>The page hit a temporary display error. Your project data and evidence were not changed.</p>
        <div className={styles.toolbar}>
          <button className={styles.primary} onClick={reset}>Try again</button>
          <a className={styles.secondary} href="/">Return to overview</a>
        </div>
      </section>
    </main>
  );
}
