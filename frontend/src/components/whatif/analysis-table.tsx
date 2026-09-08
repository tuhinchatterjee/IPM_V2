/**
 * A table CreditProbe computed from the reported book, inside a What-If
 * thread, before anything was shocked.
 *
 * Why this is a first-class part of the thread and not a link to a tab
 * ------------------------------------------------------------------
 * A person configuring a scenario asks "what are the rating-wise PDs?" for one
 * reason: they are deciding how big a shock to apply, and "increase BBB PD by
 * 20%" means something different depending on whether BBB PD is 0.18% or 1.8%.
 * Answering with "the profile views show that" sends them away from the thing
 * they were building to look something up, and then back again to type the
 * number they were missing. So the answer arrives in the thread, and the
 * follow-up narrows it in place.
 *
 * Three shapes, because three different questions were asked. A BREAKDOWN is a
 * grouped table with a Total. A BORROWERS answer is a named list, because "top
 * 20 by ECL" is about individual names and grouping them would destroy the
 * answer. A SUGGESTION is a severity ladder of magnitudes drawn from the
 * book's own history, with the instruction each one would produce — because
 * the reader asked how far to move something, and the useful reply is a
 * number they can click, not a prompt asking them for one.
 *
 * Every rate shows twice, under two names, because the two answer different
 * questions: a plain mean says what the average borrower looks like and an
 * exposure-weighted mean says what the book is exposed to.
 */

"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  WhatIfAnalysis,
  WhatIfAnalysisBorrower,
  WhatIfAnalysisCell,
  WhatIfAnalysisRow,
} from "@/lib/api";

import { count, money, pct, ResultInterpretation } from "./parts";

/** One cell, formatted by what its column actually is. */
function show(cell: WhatIfAnalysisCell | undefined, kind: string, unit: string,
              currency: string): string {
  if (!cell || cell.value === null || cell.value === undefined) return "—";
  if (kind === "count") return count(cell.value);
  if (unit === currency) return money(cell.value, currency);
  if (unit === "%") return pct(cell.value, 3);
  if (unit === "days") return `${Math.round(cell.value)}`;
  return String(cell.value);
}

/** The exposure-weighted reading of a rate, where it has one. */
function weighted(cell: WhatIfAnalysisCell | undefined, unit: string): string {
  if (!cell || cell.weighted === null || cell.weighted === undefined) return "";
  return unit === "%" ? pct(cell.weighted, 3) : String(cell.weighted);
}

function Breakdown({ body }: { body: WhatIfAnalysis }) {
  const columns = body.columns ?? [];
  const currency = body.currency ?? "SAR";
  const rows = (body.rows ?? []) as unknown as WhatIfAnalysisRow[];
  const rates = columns.filter((c) => c.kind === "rate");

  const line = (row: WhatIfAnalysisRow, isTotal = false, indent = false) => (
    <TableRow
      key={`${row.label}-${indent ? "stage" : "row"}`}
      data-row={row.label}
      className={isTotal ? "font-semibold" : undefined}
    >
      <TableCell className={indent ? "pl-8 text-muted-foreground" : undefined}>
        {row.label}
        {row.performing === false ? (
          <Badge variant="outline" className="ml-2">
            default
          </Badge>
        ) : null}
      </TableCell>
      {columns.map((column) => (
        <React.Fragment key={column.key}>
          <TableCell numeric>
            {show(row.cells?.[column.key], column.kind, column.unit, currency)}
          </TableCell>
          {column.kind === "rate" ? (
            <TableCell numeric className="text-muted-foreground">
              {weighted(row.cells?.[column.key], column.unit)}
            </TableCell>
          ) : null}
        </React.Fragment>
      ))}
    </TableRow>
  );

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{body.dimension_label ?? "Group"}</TableHead>
            {columns.map((column) => (
              <React.Fragment key={column.key}>
                <TableHead numeric>
                  {column.label}
                  {column.unit && column.unit !== currency && column.kind !== "count"
                    ? ` (${column.unit})`
                    : ""}
                </TableHead>
                {column.kind === "rate" ? (
                  <TableHead numeric>{column.label}, wtd</TableHead>
                ) : null}
              </React.Fragment>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <React.Fragment key={row.label}>
              {line(row)}
              {body.by_stage
                ? (row.by_stage ?? []).map((split) =>
                    line(split as WhatIfAnalysisRow, false, true),
                  )
                : null}
            </React.Fragment>
          ))}
          {body.total ? line(body.total, true) : null}
        </TableBody>
      </Table>
      {rates.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Each rate appears twice: the plain mean says what the average borrower
          looks like, the weighted column says what the book is exposed to.
        </p>
      ) : null}
    </div>
  );
}

function Borrowers({ body }: { body: WhatIfAnalysis }) {
  const currency = body.currency ?? "SAR";
  const rows = (body.rows ?? []) as unknown as WhatIfAnalysisBorrower[];
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Borrower</TableHead>
            <TableHead>Sector</TableHead>
            <TableHead>Rating</TableHead>
            <TableHead numeric>Stage</TableHead>
            <TableHead numeric>Exposure</TableHead>
            <TableHead numeric>Applicable PD</TableHead>
            <TableHead numeric>LGD</TableHead>
            <TableHead numeric>ECL</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.borrower_id} data-row={row.borrower_id}>
              <TableCell>{row.name || row.borrower_id}</TableCell>
              <TableCell>{row.sector}</TableCell>
              <TableCell>{row.rating}</TableCell>
              <TableCell numeric>{row.stage}</TableCell>
              <TableCell numeric>{money(row.exposure, currency)}</TableCell>
              <TableCell numeric>{pct(row.applicable_pd, 3)}</TableCell>
              <TableCell numeric>{pct(row.lgd, 2)}</TableCell>
              <TableCell numeric>{money(row.ecl, currency)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="mt-2 text-xs text-muted-foreground">
        {body.shown} of {count(body.borrowers)} borrowers, ordered by{" "}
        {body.ordered_by?.label ?? "ECL"}. They account for{" "}
        {pct(body.concentration_pct, 1)} of the population&rsquo;s total.
      </p>
    </div>
  );
}

function Suggestion({
  body,
  onUse,
}: {
  body: WhatIfAnalysis;
  onUse?: (instruction: string) => void;
}) {
  const options = body.options ?? [];
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {body.measure_label} for {body.population} at {body.period}: currently{" "}
        {pct(body.current?.weighted ?? body.current?.value, 3)} on an
        exposure-weighted basis over {count(body.borrowers)} borrowers.
      </p>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead numeric>Move</TableHead>
              <TableHead>Because</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {options.map((option) => (
              <TableRow key={option.severity} data-row={option.severity}>
                <TableCell>{option.severity}</TableCell>
                <TableCell numeric>
                  {option.magnitude}
                  {option.unit}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {option.because}
                </TableCell>
                <TableCell>
                  {onUse ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onUse(option.instruction)}
                    >
                      Use this
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">{body.measured_not_chosen}</p>
      <p className="text-sm">{body.question}</p>
    </div>
  );
}

export function AnalysisAnswer({
  body,
  onUse,
}: {
  body: WhatIfAnalysis;
  onUse?: (instruction: string) => void;
}) {
  const title =
    body.kind === "suggestion"
      ? `What this book has done to ${body.measure_label}`
      : body.kind === "borrowers"
        ? "Borrowers"
        : `${body.dimension_label} breakdown`;
  return (
    <Card data-analysis={body.kind}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline gap-2">
          <span>{title}</span>
          <Badge variant="outline">{body.period}</Badge>
          <span className="text-sm font-normal text-muted-foreground">
            {body.population}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {body.answer ? (
          <p className="text-sm font-medium">{body.answer.sentence}</p>
        ) : null}
        {body.kind === "suggestion" ? (
          <Suggestion body={body} onUse={onUse} />
        ) : body.kind === "borrowers" ? (
          <Borrowers body={body} />
        ) : (
          <Breakdown body={body} />
        )}
        {body.notes?.map((note) => (
          <p key={note} className="text-xs text-muted-foreground">
            {note}
          </p>
        ))}
        {body.measurement ? (
          <p className="text-xs text-muted-foreground">{body.measurement}</p>
        ) : null}
        {body.interpretation ? (
          <ResultInterpretation interpretation={body.interpretation} />
        ) : null}
        <p className="text-xs text-muted-foreground">
          Nothing has been shocked. This reads the reported book and leaves the
          scenario exactly as it was.
        </p>
      </CardContent>
    </Card>
  );
}
