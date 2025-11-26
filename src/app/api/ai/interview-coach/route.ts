import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { jobTitle, resumeText } = await req.json();

        if (!jobTitle) {
            return NextResponse.json({ error: "Job title is required" }, { status: 400 });
        }

        const prompt = `
      You are an expert Interview Coach.
      Job Title: ${jobTitle}
      Resume (Optional): ${resumeText || "Not provided"}
      
      Generate 3 common interview questions for this role.
      For each question, provide a sample "Good Answer" and tips on what to avoid.
      Response must be in English and Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Interview Coach API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
