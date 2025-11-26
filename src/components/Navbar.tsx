"use client";

import { Bell, User } from "lucide-react";
import { Button } from "./ui/Button";

export function Navbar() {
    return (
        <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-end border-b bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="flex items-center gap-4">
                <Button variant="ghost" size="icon">
                    <Bell className="h-5 w-5" />
                </Button>
                <Button variant="ghost" size="icon" className="rounded-full">
                    <User className="h-5 w-5" />
                </Button>
            </div>
        </header>
    );
}
