"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
    Languages,
    GraduationCap,
    TrendingUp,
    FileText,
    Scale,
    Stethoscope,
    Sprout,
    Map,
    Briefcase,
    Newspaper,
    BookOpen,
    Utensils,
    Leaf,
    Store,
    Calendar,
    HeartHandshake,
    Home,
    Menu,
    X
} from "lucide-react";
import { useState } from "react";
import { Button } from "./ui/Button";

const tools = [
    { name: "Translator", href: "/translator", icon: Languages },
    { name: "Study Helper", href: "/study-helper", icon: GraduationCap },
    { name: "Market Advisor", href: "/market-advisor", icon: TrendingUp },
    { name: "Resume Assistant", href: "/resume-assistant", icon: FileText },
    { name: "Legal Advisor", href: "/legal-advisor", icon: Scale },
    { name: "Health Assistant", href: "/health-assistant", icon: Stethoscope },
    { name: "Agri Consultant", href: "/agriculture-consultant", icon: Sprout },
    { name: "Tourism Guide", href: "/tourism-guide", icon: Map },
    { name: "Interview Coach", href: "/interview-coach", icon: Briefcase },
    { name: "News Summarizer", href: "/news-summarizer", icon: Newspaper },
    { name: "Language Tutor", href: "/language-tutor", icon: BookOpen },
    { name: "Recipe Generator", href: "/recipe-generator", icon: Utensils },
    { name: "Eco Advisor", href: "/environmental-advisor", icon: Leaf },
    { name: "Business Assistant", href: "/business-assistant", icon: Store },
    { name: "Event Planner", href: "/event-planner", icon: Calendar },
    { name: "Mental Health", href: "/mental-health", icon: HeartHandshake },
];

export function Sidebar() {
    const pathname = usePathname();
    const [isOpen, setIsOpen] = useState(false);

    return (
        <>
            {/* Mobile Toggle */}
            <Button
                variant="ghost"
                size="icon"
                className="fixed top-4 left-4 z-50 md:hidden"
                onClick={() => setIsOpen(!isOpen)}
            >
                {isOpen ? <X /> : <Menu />}
            </Button>

            {/* Sidebar */}
            <div
                className={cn(
                    "fixed inset-y-0 left-0 z-40 w-64 transform bg-card border-r transition-transform duration-200 ease-in-out md:translate-x-0",
                    isOpen ? "translate-x-0" : "-translate-x-full"
                )}
            >
                <div className="flex h-16 items-center justify-center border-b px-4">
                    <h1 className="text-xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                        Cambodia AI
                    </h1>
                </div>
                <div className="h-[calc(100vh-4rem)] overflow-y-auto py-4">
                    <nav className="space-y-1 px-2">
                        <Link
                            href="/"
                            className={cn(
                                "flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
                                pathname === "/"
                                    ? "bg-primary text-primary-foreground"
                                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                            )}
                            onClick={() => setIsOpen(false)}
                        >
                            <Home className="mr-3 h-5 w-5" />
                            Dashboard
                        </Link>
                        <div className="my-2 border-t" />
                        {tools.map((tool) => (
                            <Link
                                key={tool.href}
                                href={tool.href}
                                className={cn(
                                    "flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
                                    pathname === tool.href
                                        ? "bg-primary text-primary-foreground"
                                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                                )}
                                onClick={() => setIsOpen(false)}
                            >
                                <tool.icon className="mr-3 h-5 w-5" />
                                {tool.name}
                            </Link>
                        ))}
                    </nav>
                </div>
            </div>

            {/* Overlay for mobile */}
            {isOpen && (
                <div
                    className="fixed inset-0 z-30 bg-black/50 md:hidden"
                    onClick={() => setIsOpen(false)}
                />
            )}
        </>
    );
}
