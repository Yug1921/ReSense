import type React from "react";
import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Newsreader } from "next/font/google";
import { AuthProvider } from "@/components/auth/auth-provider";
import { ThemedToaster } from "@/components/theme/themed-toaster";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

// Serif for long-form reading (summaries and answers). Self-hosted at build time.
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500"],
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-newsreader",
});

export const metadata: Metadata = {
  title: "ReSense — Understand any research paper",
  description:
    "Upload a research paper to read it in the tone you need, ask it questions, and check its references.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
    { media: "(prefers-color-scheme: light)", color: "#f3f1ec" },
  ],
  colorScheme: "dark light",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`dark ${GeistSans.variable} ${GeistMono.variable} ${newsreader.variable}`}
      // The theme script below changes the class before React loads.
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="font-sans antialiased">
        <AuthProvider>{children}</AuthProvider>
        <ThemedToaster />
      </body>
    </html>
  );
}
