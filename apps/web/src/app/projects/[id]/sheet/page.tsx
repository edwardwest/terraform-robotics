import { SheetView } from "@/components/plan/SheetView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SheetView projectId={id} />;
}
