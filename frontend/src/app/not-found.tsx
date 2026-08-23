import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function NotFound() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Page not found</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-text-secondary">
          That address does not exist in IPM.
        </p>
        <Button asChild variant="outline" size="sm">
          <Link href="/">Back to the overview</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
