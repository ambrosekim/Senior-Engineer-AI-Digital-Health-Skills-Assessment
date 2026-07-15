import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";



export const metadata: Metadata = {
  title: "Senior Full-Stack Engineer, AI & Digital Health",
  description: "Practice interview for senior full-stack engineer role at Last Mile Health.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        
      </head>
      <body
        className="flex min-h-screen flex-col items-center justify-between p-24"
      >
        <nav className="app-nav">
          <Link href="/">Home</Link>
          <Link href="/upload">Upload PDF</Link>
        </nav>
        {children}

      </body>
    </html>
  );
}
