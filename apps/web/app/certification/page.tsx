import Link from "next/link";
import CertificationConsole from "../CertificationConsole";

export default function CertificationPage() {
  return (
    <main className="shell" style={{ display: "block", padding: "24px" }}>
      <header className="topbar" style={{ marginBottom: "18px" }}>
        <div>
          <p className="eyebrow">ADE OS · RELEASE EVIDENCE</p>
          <h1>Certification</h1>
        </div>
        <div className="top-actions">
          <Link className="ghost" href="/">Back to operator console</Link>
        </div>
      </header>
      <CertificationConsole />
    </main>
  );
}
