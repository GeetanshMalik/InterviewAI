import {
  LayoutDashboard,
  Video,
  Dumbbell,
  FileText,
  BarChart3,
  Map,
  Bot,
  Settings,
  Home,
  User,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const SIDEBAR_ITEMS: NavItem[] = [
  {
    label: "Home",
    href: "/",
    icon: Home,
  },
  {
    label: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    label: "Profile",
    href: "/profile",
    icon: User,
  },
  {
    label: "New Interview",
    href: "/interview",
    icon: Video,
  },
  {
    label: "Practice Arena",
    href: "/practice-arena",
    icon: Dumbbell,
  },
  {
    label: "Resume Analysis",
    href: "/resume-analysis",
    icon: FileText,
  },
  {
    label: "Reports",
    href: "/reports",
    icon: BarChart3,
  },
  {
    label: "Roadmaps",
    href: "/roadmaps",
    icon: Map,
  },
  {
    label: "AI Bot",
    href: "/ai-bot",
    icon: Bot,
  },
  {
    label: "Settings",
    href: "/settings",
    icon: Settings,
  },
];

export const NAVBAR_ITEMS = [
  { label: "Home", href: "/" },
  { label: "Features", href: "/features" },
  { label: "Pricing", href: "/pricing" },
  { label: "About", href: "/about" },
];
