"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, useApi, type Account, type ImportResult } from "@/lib/api";
import { IS_DEMO } from "@/lib/demo";

export default function ImportPage() {
  // Reading ?account_id= (from a link on the Accounts page) needs a Suspense boundary.
  return (
    <Suspense>{IS_DEMO ? <NotInDemo /> : <ImportForm />}</Suspense>
  );
}

/** The demo runs on made-up transactions, so there are no bank CSVs to upload. */
function NotInDemo() {
  return (
    <>
      <h1 className="text-xl font-semibold">Import</h1>
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Not available in the demo</CardTitle>
          <CardDescription>
            The demo runs on made-up transactions, so there are no bank CSVs to upload. In the
            real app, this is where you&apos;d upload a CSV downloaded from your bank.
          </CardDescription>
        </CardHeader>
      </Card>
    </>
  );
}

function ImportForm() {
  const { data: allAccounts, error: accountsError } = useApi<Account[]>("/accounts");
  // A closed account gets no new CSVs (reopen it on the Accounts page if one turns up).
  const accounts = allAccounts?.filter((a) => a.closed_on === null);
  const [accountId, setAccountId] = useState<string | null>(useSearchParams().get("account_id"));
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Default to the first account once they've loaded (or the one a link asked for).
  const selected = accountId ?? (accounts?.[0] ? String(accounts[0].id) : null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || !file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    const form = new FormData();
    form.set("account_id", selected);
    form.set("file", file);
    try {
      const done = await api<ImportResult>("/import", { method: "POST", body: form });
      setResult(done);
      toast.success(
        done.inserted === 0
          ? "Nothing new: everything in that file was already here"
          : `Imported ${done.inserted} new transaction${done.inserted === 1 ? "" : "s"}`,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="text-xl font-semibold">Import</h1>
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Upload a bank CSV</CardTitle>
          <CardDescription>
            Overlapping downloads are fine: rows already imported are skipped. If any row is
            bad, nothing is saved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {accountsError && <p className="text-sm text-destructive">{accountsError}</p>}
          <form onSubmit={submit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5 text-sm">
              Account
              <Select
                // "…" until the names load, rather than flashing the account's id.
                items={{
                  ...(selected ? { [selected]: "…" } : {}),
                  ...Object.fromEntries((accounts ?? []).map((a) => [String(a.id), a.name])),
                }}
                value={selected}
                onValueChange={(v) => setAccountId(v)}
              >
                <SelectTrigger className="w-64">
                  <SelectValue placeholder="Loading…" />
                </SelectTrigger>
                <SelectContent>
                  {(accounts ?? []).map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              CSV file
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setResult(null);
                }}
                className="text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-sm"
              />
            </label>
            <Button type="submit" disabled={!selected || !file || busy} className="w-fit">
              {busy ? "Importing…" : "Import"}
            </Button>
          </form>
          {result && (
            <p className="mt-4 text-sm" role="status">
              Added <strong>{result.inserted}</strong> new transaction
              {result.inserted === 1 ? "" : "s"}; skipped{" "}
              {result.skipped - result.from_plaid} already imported.
              {result.from_plaid > 0 &&
                ` Also skipped ${result.from_plaid} that Plaid already brought in.`}
            </p>
          )}
          {error && (
            <p className="mt-4 text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
