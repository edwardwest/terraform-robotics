import { GoalsView } from "@/components/goals/GoalsView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GoalsView projectId={id} />;
}
