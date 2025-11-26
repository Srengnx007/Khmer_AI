import Link from "next/link";
import {
  Languages,
  GraduationCap,
  TrendingUp,
  FileText,
  Scale,
  Stethoscope,
  Sprout,
  Map,
  Briefcase,
  Newspaper,
  BookOpen,
  Utensils,
  Leaf,
  Store,
  Calendar,
  HeartHandshake,
  ArrowRight
} from "lucide-react";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

const tools = [
  { name: "Translator", href: "/translator", icon: Languages, description: "Translate between Khmer and English instantly." },
  { name: "Study Helper", href: "/study-helper", icon: GraduationCap, description: "Get help with your studies and generate quizzes." },
  { name: "Market Advisor", href: "/market-advisor", icon: TrendingUp, description: "Predict crop prices and market trends." },
  { name: "Resume Assistant", href: "/resume-assistant", icon: FileText, description: "Improve your resume and get job advice." },
  { name: "Legal Advisor", href: "/legal-advisor", icon: Scale, description: "Get general legal information and advice." },
  { name: "Health Assistant", href: "/health-assistant", icon: Stethoscope, description: "Check symptoms and get health tips." },
  { name: "Agri Consultant", href: "/agriculture-consultant", icon: Sprout, description: "Diagnose plant diseases and get farming advice." },
  { name: "Tourism Guide", href: "/tourism-guide", icon: Map, description: "Plan your perfect trip in Cambodia." },
  { name: "Interview Coach", href: "/interview-coach", icon: Briefcase, description: "Practice for your next job interview." },
  { name: "News Summarizer", href: "/news-summarizer", icon: Newspaper, description: "Summarize news articles in Khmer." },
  { name: "Language Tutor", href: "/language-tutor", icon: BookOpen, description: "Learn English or Khmer with an AI tutor." },
  { name: "Recipe Generator", href: "/recipe-generator", icon: Utensils, description: "Generate delicious Khmer recipes." },
  { name: "Eco Advisor", href: "/environmental-advisor", icon: Leaf, description: "Get environmental insights and flood risks." },
  { name: "Business Assistant", href: "/business-assistant", icon: Store, description: "Grow your small business with AI." },
  { name: "Event Planner", href: "/event-planner", icon: Calendar, description: "Plan events and manage budgets." },
  { name: "Mental Health", href: "/mental-health", icon: HeartHandshake, description: "Chat with a supportive AI companion." },
];

export default function Home() {
  return (
    <div className="space-y-8">
      <div className="text-center space-y-4">
        <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
          Cambodia AI Super Platform
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
          Empowering Cambodia with Artificial Intelligence. Explore our suite of 16 powerful tools designed to help you succeed.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {tools.map((tool) => (
          <Card key={tool.href} className="flex flex-col hover:shadow-lg transition-shadow duration-200">
            <CardHeader>
              <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                <tool.icon className="w-6 h-6 text-primary" />
              </div>
              <CardTitle>{tool.name}</CardTitle>
              <CardDescription>{tool.description}</CardDescription>
            </CardHeader>
            <CardFooter className="mt-auto">
              <Button asChild className="w-full group">
                <Link href={tool.href}>
                  Open Tool
                  <ArrowRight className="ml-2 h-4 w-4 group-hover:translate-x-1 transition-transform" />
                </Link>
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
}
