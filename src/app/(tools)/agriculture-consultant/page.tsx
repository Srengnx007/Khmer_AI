"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2, Upload } from "lucide-react";

export default function AgricultureConsultantPage() {
    const [question, setQuestion] = useState("");
    const [image, setImage] = useState<string | null>(null);
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

    const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onloadend = () => {
                setImage(reader.result as string);
            };
            reader.readAsDataURL(file);
        }
    };

    const handleSubmit = async () => {
        if (!image) return;
        setLoading(true);
        try {
            const response = await fetch("/api/ai/agriculture-consultant", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question, image }),
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
                    <CardTitle>AI Agriculture Consultant</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="flex items-center justify-center w-full">
                        <label className="flex flex-col items-center justify-center w-full h-64 border-2 border-dashed rounded-lg cursor-pointer bg-gray-50 hover:bg-gray-100 dark:hover:bg-gray-800 dark:bg-gray-700 border-gray-300 dark:border-gray-600">
                            <div className="flex flex-col items-center justify-center pt-5 pb-6">
                                {image ? (
                                    <img src={image} alt="Uploaded" className="max-h-56 object-contain" />
                                ) : (
                                    <>
                                        <Upload className="w-8 h-8 mb-4 text-gray-500 dark:text-gray-400" />
                                        <p className="mb-2 text-sm text-gray-500 dark:text-gray-400">
                                            <span className="font-semibold">Click to upload</span> or drag and drop
                                        </p>
                                        <p className="text-xs text-gray-500 dark:text-gray-400">
                                            SVG, PNG, JPG or GIF (MAX. 800x400px)
                                        </p>
                                    </>
                                )}
                            </div>
                            <input type="file" className="hidden" onChange={handleImageUpload} accept="image/*" />
                        </label>
                    </div>

                    <Textarea
                        placeholder="Ask a specific question about the plant (Optional)..."
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                    />

                    <Button onClick={handleSubmit} disabled={loading || !image} className="w-full">
                        {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : "Diagnose Plant"}
                    </Button>
                </CardContent>
            </Card>

            {result && (
                <Card>
                    <CardHeader>
                        <CardTitle>Diagnosis & Advice</CardTitle>
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
