import { SceneView } from "@/components/scene/SceneView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SceneView projectId={id} />;
}
