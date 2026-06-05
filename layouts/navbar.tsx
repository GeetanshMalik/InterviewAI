"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuthStore } from "@/stores/auth-store";
import { authService } from "@/services/auth-service";
import { NAVBAR_ITEMS } from "@/constants/navigation";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils";
import { Menu, X, LogOut, Settings, User } from "lucide-react";
import { useState } from "react";

export function Navbar() {
  const pathname = usePathname();
  const { user, isAuthenticated, logout } = useAuthStore();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleLogout = async () => {
    await authService.logout();
    logout();
  };

  return (
    <nav className="sticky top-0 z-50 bg-canvas/80 backdrop-blur-lg border-b border-hairline-soft">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-14">
          <Logo size="sm" />

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-8">
            {NAVBAR_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "text-body-sm transition-colors",
                  pathname === item.href
                    ? "text-ink"
                    : "text-ink-muted hover:text-ink"
                )}
              >
                {item.label}
              </Link>
            ))}
          </div>

          {/* Desktop Actions */}
          <div className="hidden md:flex items-center gap-3">
            {isAuthenticated ? (
              <>
                <Button
                  asChild
                  variant="ghost"
                  className="text-ink hover:bg-surface-1 rounded-pill"
                >
                  <Link href={ROUTES.DASHBOARD}>Dashboard</Link>
                </Button>
                <Button
                  asChild
                  className="bg-primary text-on-primary hover:bg-primary/90 rounded-pill"
                >
                  <Link href={ROUTES.INTERVIEW}>Start Interview</Link>
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button className="rounded-md overflow-hidden">
                      <Avatar className="w-8 h-8 rounded-md">
                        <AvatarImage src={user?.avatar} />
                        <AvatarFallback className="bg-surface-1 text-ink text-caption rounded-md">
                          {user?.name?.charAt(0).toUpperCase() || "U"}
                        </AvatarFallback>
                      </Avatar>
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="bg-surface-1 border-hairline">
                    <DropdownMenuItem asChild>
                      <Link href={ROUTES.PROFILE} className="flex items-center gap-2">
                        <User className="w-4 h-4" />
                        Profile
                      </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                      <Link href={ROUTES.SETTINGS} className="flex items-center gap-2">
                        <Settings className="w-4 h-4" />
                        Settings
                      </Link>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator className="bg-hairline" />
                    <DropdownMenuItem
                      onClick={handleLogout}
                      className="flex items-center gap-2 text-gradient-orange"
                    >
                      <LogOut className="w-4 h-4" />
                      Logout
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            ) : (
              <>
                <Button
                  asChild
                  variant="ghost"
                  className="text-ink hover:bg-surface-1 rounded-pill"
                >
                  <Link href={ROUTES.LOGIN}>Login</Link>
                </Button>
                <Button
                  asChild
                  className="bg-primary text-on-primary hover:bg-primary/90 rounded-pill"
                >
                  <Link href={ROUTES.SIGNUP}>Sign Up</Link>
                </Button>
              </>
            )}
          </div>

          {/* Mobile Menu Button */}
          <button
            className="md:hidden text-ink"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          >
            {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>

        {/* Mobile Menu */}
        {mobileMenuOpen && (
          <div className="md:hidden py-4 border-t border-hairline-soft">
            <div className="flex flex-col gap-4">
              {NAVBAR_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-body text-ink-muted hover:text-ink"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  {item.label}
                </Link>
              ))}
              <div className="pt-4 border-t border-hairline-soft flex flex-col gap-2">
                {isAuthenticated ? (
                  <>
                    <Button asChild className="bg-primary text-on-primary rounded-pill">
                      <Link href={ROUTES.INTERVIEW}>Start Interview</Link>
                    </Button>
                    <Button asChild variant="outline" className="rounded-pill">
                      <Link href={ROUTES.DASHBOARD}>Dashboard</Link>
                    </Button>
                  </>
                ) : (
                  <>
                    <Button asChild className="bg-primary text-on-primary rounded-pill">
                      <Link href={ROUTES.SIGNUP}>Sign Up</Link>
                    </Button>
                    <Button asChild variant="outline" className="rounded-pill">
                      <Link href={ROUTES.LOGIN}>Login</Link>
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}
