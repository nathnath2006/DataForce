// 1.5px outline icons, rounded joins, 20px by default (docs/VISUAL-IDENTITY.md §3).
// Hand-drawn paths, no icon library: no new dependency.
import type { ReactNode } from "react";

const PATHS = {
  summary: <><rect x="3.5" y="3.5" width="7" height="9" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="5" rx="1.5" /><rect x="13.5" y="11.5" width="7" height="9" rx="1.5" /><rect x="3.5" y="15.5" width="7" height="5" rx="1.5" /></>,
  companies: <><path d="M4 20.5V5.5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v15" /><path d="M14 9.5h5a1 1 0 0 1 1 1v10" /><path d="M2.5 20.5h19M7.5 8h3M7.5 11.5h3M7.5 15h3M16.5 13h1M16.5 16.5h1" /></>,
  accounts: <><rect x="3.5" y="7.5" width="17" height="12" rx="2" /><path d="M9 7.5V5.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3.5 12.5h17" /></>,
  contacts: <><circle cx="9" cy="8.5" r="3.5" /><path d="M3 19.5c.6-3 3-5 6-5s5.4 2 6 5" /><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18 14.8c1.5.7 2.6 2.4 3 4.7" /></>,
  deals: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" /></>,
  meetings: <><rect x="3.5" y="5" width="17" height="15.5" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4" /></>,
  analysis: <><rect x="2.5" y="4" width="6" height="5" rx="1.5" /><rect x="15.5" y="4" width="6" height="5" rx="1.5" /><rect x="9" y="15" width="6" height="5" rx="1.5" /><path d="M8.5 6.5h7M5.5 9v3.5a2 2 0 0 0 2 2H9M18.5 9v3.5a2 2 0 0 1-2 2H15" /></>,
  docs: <><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" /><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
  admin: <><path d="M12 3l7.5 3v5.5c0 4.5-3.2 8-7.5 9.5-4.3-1.5-7.5-5-7.5-9.5V6z" /><path d="M9 12l2 2 4-4" /></>,
  dataset: <><ellipse cx="12" cy="6" rx="7.5" ry="2.8" /><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8" /></>,
  filter: <path d="M4 5h16l-6 7.5v6l-4 1.5v-7.5z" />,
  sort: <path d="M7 4v16M4 7l3-3 3 3M17 20V4M14 17l3 3 3-3" />,
  columns: <><rect x="3.5" y="4" width="17" height="16" rx="2" /><path d="M9.5 4v16M14.5 4v16" /></>,
  group: <><path d="M12 3.5l8.5 4.5-8.5 4.5L3.5 8z" /><path d="M3.5 12.5l8.5 4.5 8.5-4.5M3.5 16.5l8.5 4.5 8.5-4.5" /></>,
  join: <><circle cx="9" cy="12" r="5.5" /><circle cx="15" cy="12" r="5.5" /></>,
  pivot: <><rect x="3.5" y="3.5" width="17" height="17" rx="2" /><path d="M3.5 9h17M9 3.5v17" /><path d="M13 13.5h4M15 11.5v4" /></>,
  stats: <><path d="M4 20h16" /><path d="M6 20v-5M10 20V8M14 20v-8M18 20V5" /></>,
  split: <><circle cx="6" cy="6.5" r="2.5" /><circle cx="6" cy="17.5" r="2.5" /><path d="M8 8l12 9M8 16l12-9" /></>,
  model: <><path d="M4 20V4M4 20h16" /><path d="M7 16l4-4 3 2.5L20 8" /><circle cx="20" cy="8" r="1" /></>,
  cluster: <><circle cx="7" cy="8" r="1.5" /><circle cx="10" cy="5.5" r="1.5" /><circle cx="9.5" cy="10" r="1.5" /><circle cx="16" cy="15" r="1.5" /><circle cx="18.5" cy="18" r="1.5" /><circle cx="14.5" cy="18.5" r="1.5" /><circle cx="17" cy="6" r="1.5" /></>,
  chart: <><rect x="3.5" y="3.5" width="17" height="17" rx="2" /><path d="M8 16v-4M12 16V8M16 16v-6" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  send: <path d="M4.5 12L20 4.5 14 20l-2.5-6.5z M11.5 13.5L20 4.5" />,
  edit: <><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></>,
  trash: <><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13" /></>,
  history: <><path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5" /><path d="M4 4v4.5h4.5M12 8v4.5l3 2" /></>,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  chevron: <path d="M9 6l6 6-6 6" />,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 7.8v.2" /></>,
  sparkle: <path d="M12 3.5l1.8 5.2 5.2 1.8-5.2 1.8L12 17.5l-1.8-5.2L5 10.5l5.2-1.8zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  mail: <><rect x="3.5" y="5.5" width="17" height="13" rx="2" /><path d="M4 7l8 6 8-6" /></>,
  palette: <><path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.8-.8 1.8-1.7 0-1.2-1-1.6-1-2.6 0-1 .8-1.7 1.8-1.7h2.2a3.7 3.7 0 0 0 3.7-3.7c0-4.2-3.8-7.3-8.5-7.3z" /><circle cx="7.8" cy="11" r="1" /><circle cx="10.5" cy="7.3" r="1" /><circle cx="15" cy="7.8" r="1" /></>,
  key: <><circle cx="8" cy="15" r="4" /><path d="M11 12l8.5-8.5M16 7l2.5 2.5M14 9l2 2" /></>,
  plug: <><path d="M9 3.5v4M15 3.5v4M6.5 7.5h11v3a5.5 5.5 0 0 1-11 0z" /><path d="M12 16v4.5" /></>,
  robot: <><rect x="4.5" y="8" width="15" height="11" rx="3" /><path d="M12 4.5V8M9 13v1M15 13v1M2.5 13v2M21.5 13v2" /></>,
  user: <><circle cx="12" cy="8.5" r="4" /><path d="M4.5 20c.8-3.7 3.8-6 7.5-6s6.7 2.3 7.5 6" /></>,
  calendar: <><rect x="3.5" y="5" width="17" height="15.5" rx="2" /><path d="M3.5 10h17M8 3v4M16 3v4M8 14h2M14 14h2M8 17h2" /></>,
  aging: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></>,
  dedup: <><rect x="4" y="4" width="11" height="11" rx="2" /><path d="M9 20h9a2 2 0 0 0 2-2V9" /></>,
  domain: <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.5 2.5 3.5 5.3 3.5 8.5s-1 6-3.5 8.5c-2.5-2.5-3.5-5.3-3.5-8.5s1-6 3.5-8.5z" /></>,
  engagement: <><path d="M3 12h4l2.5-6 4 12 2.5-6H21" /></>,
  forecast: <><path d="M4 20V4M4 20h16" /><path d="M7 15l4-4 3 2" /><path d="M14 13l3-3 3 1" strokeDasharray="2 2" /></>,
  regex: <><path d="M12 5v9M8 7.5l8 4M16 7.5l-8 4" /><circle cx="7" cy="18" r="1" /></>,
  score: <><path d="M12 4l2.4 5 5.4.7-4 3.7 1 5.4-4.8-2.7-4.8 2.7 1-5.4-4-3.7 5.4-.7z" /></>,
  standardize: <><path d="M4 8h16M4 16h16" /><path d="M9 4v8M15 12v8" /></>,
  touchpoint: <><path d="M5 12a7 7 0 0 1 14 0" /><path d="M8 12a4 4 0 0 1 8 0" /><circle cx="12" cy="12" r="1" /><path d="M12 13v7" /></>,
  velocity: <><path d="M4 17a8 8 0 1 1 16 0" /><path d="M12 17l4-6" /></>,
  window: <><rect x="3.5" y="4" width="17" height="16" rx="2" /><path d="M3.5 9h17M8 14h8" /></>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 20, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={`icon${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
