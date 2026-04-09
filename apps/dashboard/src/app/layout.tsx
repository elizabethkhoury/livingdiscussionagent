import type { Metadata } from 'next';
import { Fraunces, IBM_Plex_Mono, Instrument_Serif } from 'next/font/google';

import './globals.css';

const display = Fraunces({
  subsets: ['latin'],
  variable: '--font-display',
});

const body = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  variable: '--font-body',
});

const mono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
});

export const metadata: Metadata = {
  title: 'PromptHunt Reddit Agent',
  description: 'Review queue, replay, health, and analytics for the Reddit agent MVP.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
