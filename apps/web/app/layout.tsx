import type { Metadata } from "next";
import "./styles.css";
import AppShell from "./_components/AppShell";

export const metadata: Metadata = {
  title: "Agentic Data Engineering OS",
  description: "Evidence-driven autonomous data engineering investigations",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><AppShell>{children}</AppShell></body></html>;
}
