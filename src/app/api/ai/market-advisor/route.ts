import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { crop, quantity, harvestDate } = await req.json();

        if (!crop) {
            return NextResponse.json({ error: "Crop type is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Agricultural Market Advisor for Cambodia.
      Crop: ${crop}
      Quantity: ${quantity}
      Harvest Date: ${harvestDate}
      
      Analyze the market trends for this crop in Cambodia.
      Predict the potential price range.
      Suggest the best time to sell.
      Provide advice on where to sell (local markets, export, etc.).
      Response must be in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Market Advisor API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
