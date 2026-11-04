interface IconProps {
  className?: string;
}

function Base({ className = '', children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`h-5 w-5 shrink-0 ${className}`}
    >
      {children}
    </svg>
  );
}

export const Icons = {
  overview: (p: IconProps) => (
    <Base {...p}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </Base>
  ),
  earlyWarning: (p: IconProps) => (
    <Base {...p}>
      <path d="M12 3 2.5 20h19L12 3z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="17" r="0.5" fill="currentColor" />
    </Base>
  ),
  image: (p: IconProps) => (
    <Base {...p}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="1.5" />
      <path d="M4 18l5-5 3 3 3-3 5 5" />
    </Base>
  ),
  geo: (p: IconProps) => (
    <Base {...p}>
      <path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11z" />
      <circle cx="12" cy="10" r="2.5" />
    </Base>
  ),
  reports: (p: IconProps) => (
    <Base {...p}>
      <path d="M6 2h9l4 4v16H6V2z" />
      <path d="M14 2v5h5" />
      <path d="M9 13h7M9 17h7" />
    </Base>
  ),
  verification: (p: IconProps) => (
    <Base {...p}>
      <path d="M12 2l8 3v6c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V5l8-3z" />
      <path d="M9 12l2 2 4-4" />
    </Base>
  ),
  collapse: (p: IconProps) => (
    <Base {...p}>
      <path d="M14 6l-6 6 6 6" />
    </Base>
  ),
  expand: (p: IconProps) => (
    <Base {...p}>
      <path d="M10 6l6 6-6 6" />
    </Base>
  ),
  menu: (p: IconProps) => (
    <Base {...p}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Base>
  ),
  close: (p: IconProps) => (
    <Base {...p}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Base>
  ),
};

export type IconName = keyof typeof Icons;
