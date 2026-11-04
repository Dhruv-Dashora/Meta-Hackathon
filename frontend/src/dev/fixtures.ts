// Dev-only UI fixtures for layout work without API calls.
// Active only when VITE_DEMO_FIXTURE === 'true'. Never user-facing
// otherwise, and never mistaken for real analysis (bannered).

export const FIXTURE_MODE = import.meta.env.VITE_DEMO_FIXTURE === 'true';

// Clearly synthetic placeholder image (SVG data URL, labeled as fixture).
export const FIXTURE_IMAGE_URL =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">
      <rect width="640" height="480" fill="#e2e8f0"/>
      <g stroke="#cbd5e1" stroke-width="1">
        <path d="M0 120h640M0 240h640M0 360h640M160 0v480M320 0v480M480 0v480"/>
      </g>
      <text x="320" y="240" font-family="sans-serif" font-size="28" fill="#64748b" text-anchor="middle">
        Fixture image — layout only
      </text>
    </svg>`,
  );
