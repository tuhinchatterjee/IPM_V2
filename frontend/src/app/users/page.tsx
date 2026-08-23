"use client";

import * as React from "react";
import { Check, Minus, Users as UsersIcon } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { useRole } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { DEMO_NOTICE, ROLE_MATRIX, TEAMS, USERS } from "@/lib/demo";

/**
 * Users, teams and the permission model.
 *
 * The users and teams are demo records, but the role matrix is real: it mirrors
 * backend/api/permissions.py, and the role selected in the header genuinely
 * changes what the API allows.
 */
export default function UsersPage() {
  const [tab, setTab] = React.useState("users");
  const { role } = useRole();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users & Teams"
        description="Who may do what. Access is enforced at three levels: capability, object and data."
        status="preview"
        phase="Demo records · real permission model"
      />

      <Card className="p-4 text-sm text-text-secondary">
        You are acting as <strong className="text-text-primary">{role}</strong>. Change it in the
        header — the role is sent to the API on every request, so a Viewer genuinely cannot
        publish a dataset. This demonstrates the permission model; it is not authentication.
      </Card>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "users", label: "Users", count: USERS.length },
          { id: "teams", label: "Teams", count: TEAMS.length },
          { id: "roles", label: "Roles & Permissions" },
        ]}
      />

      {tab === "users" && (
        <Card>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Team</TableHead>
                <TableHead>Last active</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {USERS.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium text-text-primary">{u.name}</TableCell>
                  <TableCell className="font-mono text-xs">{u.email}</TableCell>
                  <TableCell><Badge variant="outline">{u.role}</Badge></TableCell>
                  <TableCell className="text-xs">{u.team}</TableCell>
                  <TableCell className="text-xs">{u.lastActive}</TableCell>
                  <TableCell>
                    <Badge variant={u.status === "active" ? "positive" : "default"}>
                      {u.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      {tab === "teams" && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {TEAMS.map((t) => (
            <Card key={t.id} className="p-5">
              <UsersIcon className="mb-3 size-5 text-text-muted" aria-hidden />
              <h3 className="text-sm font-semibold text-text-primary">{t.name}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-text-muted">{t.purpose}</p>
              <div className="mt-4 flex gap-6 border-t border-border pt-3 text-xs">
                <span className="text-text-muted">
                  <strong className="text-text-primary tabular">{t.members}</strong> members
                </span>
                <span className="text-text-muted">
                  <strong className="text-text-primary tabular">{t.projects}</strong> projects
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}

      {tab === "roles" && (
        <Card>
          <div className="border-b border-border px-5 py-3">
            <h3 className="text-sm font-semibold text-text-primary">Capability matrix</h3>
            <p className="mt-0.5 text-xs text-text-muted">
              Mirrors the rules the backend enforces on every request.
            </p>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Capability</TableHead>
                <TableHead>Administrator</TableHead>
                <TableHead>Data Steward</TableHead>
                <TableHead>Analyst</TableHead>
                <TableHead>Viewer</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ROLE_MATRIX.map((row) => (
                <TableRow key={row.capability}>
                  <TableCell className="text-text-primary">{row.capability}</TableCell>
                  {(["ADMIN", "DATA_STEWARD", "ANALYST", "VIEWER"] as const).map((r) => (
                    <TableCell key={r}>
                      {row[r] ? (
                        <Check className="size-4 text-positive" aria-label="allowed" />
                      ) : (
                        <Minus className="size-4 text-text-muted" aria-label="not allowed" />
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <p className="text-xs text-text-muted">{DEMO_NOTICE}</p>
    </div>
  );
}
