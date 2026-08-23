"use client";

import * as React from "react";
import { CheckCircle2, Clock, Inbox } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { DEMO_NOTICE, WORKFLOW_ITEMS } from "@/lib/demo";

export default function WorkflowPage() {
  const [tab, setTab] = React.useState("inbox");
  const open = WORKFLOW_ITEMS.filter((w) => w.state === "submitted" || w.state === "in_review");
  const closed = WORKFLOW_ITEMS.filter((w) => w.state === "approved" || w.state === "rejected");
  const rows = tab === "inbox" ? open : tab === "closed" ? closed : WORKFLOW_ITEMS;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflow"
        description="Review and approval of things that carry institutional weight: certifying an analysis, publishing a dataset, approving a scenario, signing off a paper."
        status="preview"
        phase="Demo records"
      />

      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ["Awaiting action", open.length, Inbox],
          ["In review", WORKFLOW_ITEMS.filter((w) => w.state === "in_review").length, Clock],
          ["Approved", WORKFLOW_ITEMS.filter((w) => w.state === "approved").length, CheckCircle2],
        ].map(([label, value, Icon]) => {
          const I = Icon as typeof Inbox;
          return (
            <Card key={String(label)} className="p-4">
              <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
                <I className="size-3.5" aria-hidden />
                {String(label)}
              </p>
              <p className="mt-1.5 text-2xl font-semibold text-text-primary tabular">{String(value)}</p>
            </Card>
          );
        })}
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "inbox", label: "Approval Inbox", count: open.length },
          { id: "closed", label: "Closed", count: closed.length },
          { id: "all", label: "All", count: WORKFLOW_ITEMS.length },
        ]}
      />

      <Card>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Item</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Requested by</TableHead>
              <TableHead>Assigned to</TableHead>
              <TableHead>Due</TableHead>
              <TableHead>State</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((w) => (
              <TableRow key={w.id}>
                <TableCell className="font-medium text-text-primary">{w.title}</TableCell>
                <TableCell><Badge variant="outline">{w.objectType}</Badge></TableCell>
                <TableCell className="text-xs">{w.requestedBy}</TableCell>
                <TableCell className="text-xs">{w.assignedTo}</TableCell>
                <TableCell className="text-xs">{w.due}</TableCell>
                <TableCell>
                  <Badge
                    variant={
                      w.state === "approved" ? "positive"
                        : w.state === "rejected" ? "negative"
                        : w.state === "in_review" ? "warning" : "accent"
                    }
                  >
                    {w.state.replace("_", " ")}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button variant="ghost" size="sm" disabled title="Workflow transitions are not built yet">
                    Review
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <p className="text-xs text-text-muted">
        {DEMO_NOTICE} The workflow tables — items and an append-only event log — already exist in
        PostgreSQL; state transitions from this screen are not wired up.
      </p>
    </div>
  );
}
