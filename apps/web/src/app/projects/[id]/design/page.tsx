import { DesignView } from "@/components/design/DesignView";
import { MasterPlanView } from "@/components/plan/MasterPlanView";

export default async function Page({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tool?: string; mode?: string }>;
}) {
  const { id } = await params;
  const { tool, mode } = await searchParams;
  if (mode === "plan") return <MasterPlanView projectId={id} />;
  return <DesignView projectId={id} initialTool={tool === "swale" ? "swale" : "keyline"} />;
}
