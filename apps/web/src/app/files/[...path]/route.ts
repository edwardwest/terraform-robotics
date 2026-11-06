import { proxy } from "@/lib/server/proxy";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };
const handle = async (req: Request, { params }: Ctx) => proxy(req, "/files", (await params).path);

export { handle as GET };
