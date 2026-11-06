import { TerrainView } from "@/components/terrain/TerrainView";

export default async function TerrainPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TerrainView projectId={id} />;
}
