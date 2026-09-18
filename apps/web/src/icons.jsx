export function IconLive() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        d="M3 12h4l2-6 4 12 2-6h6"
      />
    </svg>
  );
}

export function IconCatalog() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="3" width="8" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="3" width="8" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="3" y="13" width="8" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="13" width="8" height="8" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function IconRun() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M8 5.5v13l11-6.5L8 5.5z" />
    </svg>
  );
}

export function IconTape() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        d="M5 6h14M5 12h14M5 18h10"
      />
    </svg>
  );
}

export function IconFixtures() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        d="M4 8h16v11H4zM4 8l2-4h12l2 4"
      />
    </svg>
  );
}

export function IconChevron({ left }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        d={left ? "M14 6l-6 6 6 6" : "M10 6l6 6-6 6"}
      />
    </svg>
  );
}

export function IconMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path fill="none" stroke="currentColor" strokeWidth="1.6" d="M12 8v5M12 15.5v.5" />
    </svg>
  );
}

export function IconApi() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        d="M8 7H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h3M16 7h3a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-3M10 12h4"
      />
    </svg>
  );
}

export function IconDatabase() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <ellipse cx="12" cy="6" rx="7" ry="3" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"
      />
    </svg>
  );
}

export function IconQueue() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="4" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="4" y="10" width="16" height="4" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <rect x="4" y="15" width="16" height="4" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function IconClock() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path fill="none" stroke="currentColor" strokeWidth="1.6" d="M12 8v5l3 2" />
    </svg>
  );
}

export const FAULT_ICONS = {
  redis_down: IconDatabase,
  handler_latency: IconClock,
  worker_drop: IconQueue,
};

export function IconGameDay() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="4" y="5" width="16" height="15" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path fill="none" stroke="currentColor" strokeWidth="1.6" d="M8 3v4M16 3v4M4 10h16" />
    </svg>
  );
}

export const NAV = [
  { id: "ops", label: "Console", Icon: IconLive },
  { id: "gameday", label: "Game day", Icon: IconGameDay },
  { id: "tape", label: "Tape", Icon: IconTape },
  { id: "fixtures", label: "Fixtures", Icon: IconFixtures },
];
