import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Agentic Data Engineering OS",
  description: "Operator console for deterministic data engineering intelligence, quality, lineage, and migration",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
