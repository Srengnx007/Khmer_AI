import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { ingredients } = await req.json();

        if (!ingredients) {
            return NextResponse.json({ error: "Ingredients are required" }, { status: 400 });
        }

        const prompt = `
      You are an expert Khmer Chef.
      Ingredients: ${ingredients}
      
      Suggest a delicious Khmer dish that can be made with these ingredients.
      Provide the recipe name, ingredients list, and step-by-step cooking instructions in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Recipe Generator API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
