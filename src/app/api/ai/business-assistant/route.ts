import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { productInfo, goal } = await req.json();

        if (!productInfo) {
            return NextResponse.json({ error: "Product info is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Small Business Assistant.
      Product/Service: ${productInfo}
      Goal: ${goal || "General Marketing"}
      
      Generate a marketing plan.
      Include 3 catchy slogans in Khmer.
      Write a sample Facebook post in Khmer.
      Suggest a basic business strategy.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Business Assistant API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
