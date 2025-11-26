"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2 } from "lucide-react";

export default function MarketAdvisorPage() {
    const [crop, setCrop] = useState("");
    const [quantity, setQuantity] = useState("");
    const [harvestDate, setHarvestDate] = useState("");
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async () => {
        if (!crop) return;
        setLoading(true);
        try {
            const response = await fetch("/api/ai/market-advisor", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ crop, quantity, harvestDate }),
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
                    <CardTitle>AI Market Advisor</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <Input
                        placeholder="Crop Name (e.g., Rice, Mango)"
                        value={crop}
                        onChange={(e) => setCrop(e.target.value)}
                    />
                    <Input
                        placeholder="Quantity (e.g., 1000 kg)"
                        value={quantity}
                        onChange={(e) => setQuantity(e.target.value)}
                    />
                    <Input
                        type="date"
                        placeholder="Harvest Date"
                        value={harvestDate}
                        onChange={(e) => setHarvestDate(e.target.value)}
                    />
                    <Button onClick={handleSubmit} disabled={loading} className="w-full">
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Analyze Market"}
                    </Button>
                </CardContent>
            </Card>

            {result && (
                <Card>
                    <CardHeader>
                        <CardTitle>Market Analysis</CardTitle>
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
