"use client";

import Link, { type LinkProps } from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { scopedLink } from "../../lib/client-workspace";

type Props = Omit<LinkProps, "href"> & {
  href: string;
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
};

/**
 * Keep the server and first client render identical, then add the browser's
 * project/environment scope after hydration.
 */
export default function ScopedLink({ href, children, ...props }: Props) {
  const [resolvedHref, setResolvedHref] = useState(href);
  useEffect(() => {
    const resolve = () => setResolvedHref(scopedLink(href));
    resolve();
    window.addEventListener("ade-workspace-scope-change", resolve);
    return () => window.removeEventListener("ade-workspace-scope-change", resolve);
  }, [href]);
  return <Link {...props} href={resolvedHref}>{children}</Link>;
}
