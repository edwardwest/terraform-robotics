import { ExportView } from "@/components/estimate/ExportView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ExportView projectId={id} />;
}
