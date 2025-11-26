import { GoogleGenerativeAI } from "@google/generative-ai";

const apiKey = process.env.GEMINI_API_KEY;

if (!apiKey) {
    console.warn("GEMINI_API_KEY is not set in environment variables.");
}

const genAI = new GoogleGenerativeAI(apiKey || "");

export async function generateAIResponse(
    prompt: string,
    modelName: string = "gemini-2.0-flash",
    imageParts?: { inlineData: { data: string; mimeType: string } }[]
) {
    try {
        const model = genAI.getGenerativeModel({ model: modelName });

        let result;
        if (imageParts && imageParts.length > 0) {
            result = await model.generateContent([prompt, ...imageParts]);
        } else {
            result = await model.generateContent(prompt);
        }

        const response = await result.response;
        return response.text();
    } catch (error) {
        console.error("Error generating AI response:", error);
        throw error;
    }
}
