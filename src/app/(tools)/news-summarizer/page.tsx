"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2 } from "lucide-react";

export default function NewsSummarizerPage() {
    const [articleText, setArticleText] = useState("");
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async () => {
        if (!articleText) return;
        setLoading(true);
        try {
            const response = await fetch("/api/ai/news-summarizer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ articleText }),
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
                    <CardTitle>AI News Summarizer</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <Textarea
                        placeholder="Paste news article here..."
                        value={articleText}
                        onChange={(e) => setArticleText(e.target.value)}
                        className="min-h-[200px]"
                    />
                    <Button onClick={handleSubmit} disabled={loading} className="w-full">
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Summarize in Khmer"}
                    </Button>
                </CardContent>
            </Card>

            {result && (
                <Card>
                    <CardHeader>
                        <CardTitle>Summary</CardTitle>
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
