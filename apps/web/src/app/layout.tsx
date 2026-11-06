import type { Metadata, Viewport } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "@/styles/globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import { AppHeader } from "@/components/AppHeader";
import { clerkAppearance } from "@/lib/clerkAppearance";

export const metadata: Metadata = {
  title: "Terraform Robotics",
  description: "Site survey to permaculture design.",
  icons: { icon: "/brand/terraform-robotics-mark.svg" },
};

export const viewport: Viewport = {
  themeColor: "#000000",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider appearance={clerkAppearance} afterSignOutUrl="/sign-in">
      <html lang="en">
        <body>
          <AppHeader />
          <main id="main">{children}</main>
        </body>
      </html>
    </ClerkProvider>
  );
}
