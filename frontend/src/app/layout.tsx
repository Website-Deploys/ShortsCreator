import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Providers } from "@/app/providers";

import "@/app/globals.css";

export const metadata: Metadata = {
  title: "Project Olympus",
  description: "Turn one long-form video into multiple premium, creator-ready Shorts.",
};

/** Root layout: applies global styles and wraps the app in client providers. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
