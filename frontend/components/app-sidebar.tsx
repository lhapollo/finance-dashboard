"use client";

import {
  ArrowLeftRightIcon,
  LandmarkIcon,
  LayoutDashboardIcon,
  MessageCircleIcon,
  PiggyBankIcon,
  UploadIcon,
  WalletIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboardIcon },
  { href: "/transactions", label: "Transactions", icon: ArrowLeftRightIcon },
  { href: "/import", label: "Import", icon: UploadIcon },
  // Later phases; shown so the layout matches the plan.
  { href: null, label: "Buckets", icon: PiggyBankIcon },
  { href: null, label: "Accounts", icon: LandmarkIcon },
  { href: null, label: "Ask", icon: MessageCircleIcon },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex shrink-0 flex-col gap-6 bg-sidebar px-3 py-5 text-sidebar-foreground md:w-56">
      <div className="flex items-center gap-2 px-2 font-semibold text-sidebar-primary">
        <WalletIcon className="size-5" />
        <span>FinDash</span>
      </div>
      <nav className="flex gap-1 overflow-x-auto md:flex-col">
        {NAV.map(({ href, label, icon: Icon }) =>
          href ? (
            <Link
              key={label}
              href={href}
              aria-current={pathname === href ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm whitespace-nowrap transition-colors hover:bg-sidebar-accent",
                pathname === href && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          ) : (
            <span
              key={label}
              className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm whitespace-nowrap opacity-50"
              title="Coming in a later phase"
            >
              <Icon className="size-4" />
              {label}
              <span className="ml-auto text-[10px] tracking-wide uppercase">Soon</span>
            </span>
          ),
        )}
      </nav>
    </aside>
  );
}
