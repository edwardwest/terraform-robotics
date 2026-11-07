import { IdeasView } from "@/components/ideas/IdeasView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <IdeasView projectId={id} />;
}
