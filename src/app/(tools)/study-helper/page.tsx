"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2 } from "lucide-react";

export default function StudyHelperPage() {
    const [question, setQuestion] = useState("");
    const [subject, setSubject] = useState("");
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async () => {
        if (!question) return;
        setLoading(true);
        try {
            const response = await fetch("/api/ai/study-helper", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question, subject }),
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
                    <CardTitle>AI Study Helper</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <Input
                        placeholder="Subject (Optional)"
                        value={subject}
                        onChange={(e) => setSubject(e.target.value)}
                    />
                    <Textarea
                        placeholder="Ask your question here..."
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        className="min-h-[150px]"
                    />
                    <Button onClick={handleSubmit} disabled={loading} className="w-full">
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Get Explanation"}
                    </Button>
                </CardContent>
            </Card>

            {result && (
                <Card>
                    <CardHeader>
                        <CardTitle>Explanation</CardTitle>
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
