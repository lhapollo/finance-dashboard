import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Toaster } from "sonner";

import { AppSidebar } from "@/components/app-sidebar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "FinDash",
  description: "Where my money goes",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // translate="no": browsers shouldn't "translate" merchant names (Chrome turned
    // "Presto Fare" into "Hurry up", reading it as Italian).
    <html lang="en" translate="no" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col md:flex-row">
        <AppSidebar />
        <main className="flex min-w-0 flex-1 flex-col gap-4 p-4 md:p-6">{children}</main>
        <Toaster position="bottom-right" theme="system" duration={3000} />
      </body>
    </html>
  );
}
