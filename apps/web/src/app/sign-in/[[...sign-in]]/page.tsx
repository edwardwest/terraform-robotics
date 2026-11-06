import { SignIn } from "@clerk/nextjs";
import { AuthLayout } from "@/components/auth/AuthLayout";

export const metadata = { title: "Sign in · Terraform Robotics" };

export default function SignInPage() {
  return (
    <AuthLayout title="Start with the land.">
      <SignIn />
    </AuthLayout>
  );
}
