import { EstimateView } from "@/components/estimate/EstimateView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EstimateView projectId={id} />;
}
