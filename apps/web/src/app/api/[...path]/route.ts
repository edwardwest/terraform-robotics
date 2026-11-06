import { proxy } from "@/lib/server/proxy";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };
const handle = async (req: Request, { params }: Ctx) => proxy(req, "/api", (await params).path);

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
