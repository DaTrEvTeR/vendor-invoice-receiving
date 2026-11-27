import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Invoice Receiving",
  description: "Load vendor invoices, review how they were read, and receive stock.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <span className="brand">Invoice Receiving</span>
          <nav>
            <Link href="/">Invoices</Link>
            <Link href="/inventory">Inventory</Link>
            <Link href="/purchase-orders">Purchase orders</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
