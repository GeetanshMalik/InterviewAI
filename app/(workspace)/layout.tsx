import { WorkspaceLayout } from "@/layouts/workspace-layout";
import { ProtectedRoute } from "@/components/protected-route";

export default function WorkspaceRouteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedRoute>
      <WorkspaceLayout>{children}</WorkspaceLayout>
    </ProtectedRoute>
  );
}
