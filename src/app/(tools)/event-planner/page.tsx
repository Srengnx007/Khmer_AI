"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2 } from "lucide-react";

export default function EventPlannerPage() {
    const [eventType, setEventType] = useState("");
    const [guestCount, setGuestCount] = useState("");
    const [location, setLocation] = useState("");
    const [budget, setBudget] = useState("");
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async () => {
        if (!eventType) return;
        setLoading(true);
        try {
            const response = await fetch("/api/ai/event-planner", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ eventType, guestCount, location, budget }),
            });
            const data = await response.json();
            setResult(data.result);
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="max-w-2xl mx-auto space-y-6">
            <Card>
                <CardHeader>
                    <CardTitle>AI Event Planner</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <Input
                        placeholder="Event Type (e.g., Wedding, Birthday)..."
                        value={eventType}
                        onChange={(e) => setEventType(e.target.value)}
                    />
                    <Input
                        placeholder="Number of Guests"
                        value={guestCount}
                        onChange={(e) => setGuestCount(e.target.value)}
                    />
                    <Input
                        placeholder="Location"
                        value={location}
                        onChange={(e) => setLocation(e.target.value)}
                    />
                    <Input
                        placeholder="Budget"
                        value={budget}
                        onChange={(e) => setBudget(e.target.value)}
                    />
                    <Button onClick={handleSubmit} disabled={loading} className="w-full">
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Plan Event"}
                    </Button>
                </CardContent>
            </Card>

            {result && (
                <Card>
                    <CardHeader>
                        <CardTitle>Event Plan</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap">
                            {result}
                        </div>
                    </CardContent>
                </Card>
            )}
        </div>
    );
}
