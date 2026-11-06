import { SurveySources } from "@/components/survey/SurveySources";

export default async function SurveyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SurveySources projectId={id} />;
}
