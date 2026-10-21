import type React from "react";
import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Newsreader } from "next/font/google";
import { Toaster } from "sonner";
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
  themeColor: "#0a0a0a",
  colorScheme: "dark",
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
    >
      <body className="font-sans antialiased">
        {children}
        <Toaster
          theme="dark"
          position="top-center"
          toastOptions={{
            classNames: {
              toast: "!bg-raised !border-border !text-foreground",
              description: "!text-muted-foreground",
            },
          }}
        />
      </body>
    </html>
  );
}
