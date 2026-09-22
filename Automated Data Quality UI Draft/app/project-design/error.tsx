"use client";

export default function ProjectDesignError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, background: "#f4f6f5", color: "#17211e", fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif" }}>
      <section style={{ width: "min(100%, 560px)", padding: 28, border: "1px solid #dce3df", borderRadius: 12, background: "#fff" }}>
        <p style={{ margin: 0, color: "#84908b", fontSize: 12, fontWeight: 800, letterSpacing: 1.2 }}>LINEAGE</p>
        <h1 style={{ margin: "8px 0", fontSize: 26 }}>Lineage could not load</h1>
        <p style={{ color: "#6f7b75", lineHeight: 1.5 }}>The page hit an unexpected error while loading this project’s analysis. Retry the page; if the error continues, reload the app to fetch the current page version.</p>
        {error.digest && <p style={{ color: "#6f7b75", fontSize: 12 }}>Reference: {error.digest}</p>}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 20 }}>
          <button onClick={reset} style={{ minHeight: 40, padding: "8px 14px", border: "1px solid #17835b", borderRadius: 8, background: "#17835b", color: "#fff", fontWeight: 700 }}>Try again</button>
          <button onClick={() => window.location.reload()} style={{ minHeight: 40, padding: "8px 14px", border: "1px solid #dce3df", borderRadius: 8, background: "#fff", color: "#34403c", fontWeight: 700 }}>Reload page</button>
        </div>
      </section>
    </main>
  );
}
