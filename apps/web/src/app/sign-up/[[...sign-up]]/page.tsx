import { SignUp } from "@clerk/nextjs";
import { AuthLayout } from "@/components/auth/AuthLayout";

export const metadata = { title: "Create an account · Terraform Robotics" };

export default function SignUpPage() {
  return (
    <AuthLayout title="Design with the water, not against it.">
      <SignUp />
    </AuthLayout>
  );
}
