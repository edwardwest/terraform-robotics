import { SiteSetup } from "@/components/site/SiteSetup";

export default async function SitePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SiteSetup projectId={id} />;
}
