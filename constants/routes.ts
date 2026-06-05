export const ROUTES = {
  HOME: "/",
  LOGIN: "/login",
  SIGNUP: "/signup",
  PROFILE: "/profile",
  DASHBOARD: "/dashboard",
  INTERVIEW: "/interview",
  PRACTICE_ARENA: "/practice-arena",
  RESUME_ANALYSIS: "/resume-analysis",
  REPORTS: "/reports",
  ROADMAPS: "/roadmaps",
  AI_BOT: "/ai-bot",
  SETTINGS: "/settings",
} as const;

export const PUBLIC_ROUTES = [ROUTES.HOME, ROUTES.LOGIN, ROUTES.SIGNUP];

export const PROTECTED_ROUTES = [
  ROUTES.DASHBOARD,
  ROUTES.PROFILE,
  ROUTES.INTERVIEW,
  ROUTES.PRACTICE_ARENA,
  ROUTES.RESUME_ANALYSIS,
  ROUTES.REPORTS,
  ROUTES.ROADMAPS,
  ROUTES.AI_BOT,
  ROUTES.SETTINGS,
];
