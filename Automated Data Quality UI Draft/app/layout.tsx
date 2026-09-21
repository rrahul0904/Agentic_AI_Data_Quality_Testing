import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./reset.css";

export const metadata: Metadata = {
  title: "Automated Data Quality Tool",
  description: "Evidence-grounded automated data quality and pipeline assurance control plane.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
