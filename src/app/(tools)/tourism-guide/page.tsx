"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2 } from "lucide-react";

export default function TourismGuidePage() {
    const [city, setCity] = useState("");
    const [duration, setDuration] = useState("");
    const [interests, setInterests] = useState("");
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async () => {
        if (!city) return;
        setLoading(true);
        try {
            const response = await fetch("/api/ai/tourism-guide", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ city, duration, interests }),
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
                    <CardTitle>AI Tourism Guide</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <Input
                        placeholder="City/Destination (e.g., Siem Reap)"
                        value={city}
                        onChange={(e) => setCity(e.target.value)}
                    />
                    <Input
                        placeholder="Duration (e.g., 3 days)"
                        value={duration}
                        onChange={(e) => setDuration(e.target.value)}
                    />
                    <Input
                        placeholder="Interests (e.g., History, Food, Nature)"
                        value={interests}
                        onChange={(e) => setInterests(e.target.value)}
                    />
                    <Button onClick={handleSubmit} disabled={loading} className="w-full">
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Generate Itinerary"}
                    </Button>
                </CardContent>
            </Card>

            {result && (
                <Card>
                    <CardHeader>
                        <CardTitle>Travel Itinerary</CardTitle>
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
