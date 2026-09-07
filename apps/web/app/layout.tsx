import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "UMA — Unified Data Migration Accelerator",
  description: "Governed migration operations with durable evidence",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
