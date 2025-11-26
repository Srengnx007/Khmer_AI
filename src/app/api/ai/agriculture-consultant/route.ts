import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { image, question } = await req.json();

        if (!image) {
            return NextResponse.json({ error: "Image is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Agriculture Consultant for Cambodia.
      Analyze the image of the plant/crop.
      Identify any diseases, pests, or nutrient deficiencies.
      Provide solutions and treatment recommendations.
      If a specific question is asked, answer it.
      Question: ${question || "Diagnose this plant."}
      Response must be in Khmer.
    `;

        // Image is expected to be a base64 string (without data:image/...;base64, prefix if possible, or we strip it)
        const base64Image = image.replace(/^data:image\/(png|jpeg|jpg|webp);base64,/, "");

        const imageParts = [
            {
                inlineData: {
                    data: base64Image,
                    mimeType: "image/jpeg", // Assuming jpeg for simplicity, or detect from header
                },
            },
        ];

        const result = await generateAIResponse(prompt, "gemini-2.0-flash", imageParts);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Agriculture Consultant API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
