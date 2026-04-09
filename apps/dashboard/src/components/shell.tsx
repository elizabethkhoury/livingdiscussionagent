import Link from 'next/link';

type NavItem = {
  href: string;
  label: string;
};

const navItems: NavItem[] = [
  { href: '/queue', label: 'Queue' },
  { href: '/health', label: 'Health' },
  { href: '/analytics', label: 'Analytics' },
];

export function Shell({
  active,
  children,
}: Readonly<{
  active: string;
  children: React.ReactNode;
}>) {
  return (
    <main className="app-shell">
      <section className="masthead">
        <div className="masthead-card">
          <span className="eyebrow">Editorial Control Room</span>
          <h1 className="headline">Review the agent before Reddit ever sees it.</h1>
          <p className="subcopy">
            Every candidate carries a route decision, critic pass, safety posture, and replay
            trace. The operator surface stays manual on posting, automatic on learning, and
            legible all the way through.
          </p>
          <div className="nav-strip">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="nav-chip"
                data-active={item.href === active}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
      </section>
      {children}
    </main>
  );
}
