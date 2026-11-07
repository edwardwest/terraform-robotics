import { DesignView } from "@/components/design/DesignView";

export default async function Page({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tool?: string }>;
}) {
  const { id } = await params;
  const { tool } = await searchParams;
  return <DesignView projectId={id} initialTool={tool === "swale" ? "swale" : "keyline"} />;
}
