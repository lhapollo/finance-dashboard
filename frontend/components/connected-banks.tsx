"use client";

import { useEffect, useState } from "react";
import { usePlaidLink, type PlaidLinkOnSuccessMetadata } from "react-plaid-link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  api,
  useApi,
  type Account,
  type PlaidAccount,
  type PlaidItem,
  type PlaidStatus,
  type SyncResult,
} from "@/lib/api";
import { formatDay, timeAgo, toIsoDate } from "@/lib/format";

/** "Don't import" in the account dropdowns. */
const SKIP = "skip";

/**
 * Banks connected through Plaid: which of my accounts each one feeds, when it last synced,
 * and buttons to sync, reconnect, or connect another bank.
 *
 * Connecting: we ask our backend for a link token, which opens Plaid Link (Plaid's login
 * pop-up). You log in to your bank there, so your bank password only ever goes to Plaid.
 * Plaid Link then gives us a temporary public token, and the backend swaps it for the
 * permanent access token it keeps (encrypted) to read your transactions.
 */
export function ConnectedBanks({
  syncKey,
  onChanged,
}: {
  syncKey: number; // bumped when the page's automatic sync finished
  onChanged: () => void; // transactions changed: reload the page's numbers
}) {
  const { data: status } = useApi<PlaidStatus>("/plaid/status");
  const { data: items, error: loadError, reload } = useApi<PlaidItem[]>("/plaid/items", syncKey);
  const [link, setLink] = useState<{ token: string; itemId: number | null } | null>(null);
  const [busy, setBusy] = useState<"connect" | "sync" | null>(null);
  const [results, setResults] = useState<SyncResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function sync() {
    setBusy("sync");
    setError(null);
    try {
      const done = await api<SyncResult[]>("/plaid/sync?force=true", { method: "POST" });
      setResults(done);
      reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  /** Opens Plaid Link: for a new bank, or with `itemId`, to log in to that one again. */
  async function openLink(itemId: number | null) {
    setBusy("connect");
    setError(null);
    try {
      const path = itemId === null ? "/plaid/link-token" : `/plaid/link-token?item_id=${itemId}`;
      const { link_token } = await api<{ link_token: string }>(path, { method: "POST" });
      setLink({ token: link_token, itemId }); // PlaidLauncher opens Link once it has loaded
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function linkFinished(publicToken: string, metadata: PlaidLinkOnSuccessMetadata) {
    const reconnecting = link?.itemId !== null;
    setLink(null);
    try {
      // Reconnecting fixes the existing login, so there's no new token to save.
      if (!reconnecting) {
        await api("/plaid/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            public_token: publicToken,
            institution_name: metadata.institution?.name ?? "Unknown bank",
          }),
        });
      }
      reload();
      if (reconnecting) await sync();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function remove(item: PlaidItem) {
    const sure = window.confirm(
      `Disconnect ${item.institution_name}? Plaid stops reading this bank, and its accounts go ` +
        "back to CSV imports. Transactions already imported stay.",
    );
    if (!sure) return;
    setError(null);
    try {
      await api(`/plaid/items/${item.id}`, { method: "DELETE" });
      reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const sandbox = status?.environment === "sandbox";
  const current = (items ?? []).filter((i) => i.environment === status?.environment);
  const other = (items ?? []).filter((i) => i.environment !== status?.environment);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Connected banks
          {sandbox && <Badge variant="secondary">Sandbox: test banks only</Badge>}
        </CardTitle>
        <CardDescription>
          {sandbox ? (
            <>
              Plaid is in test mode: pick any bank and log in with <code>user_good</code> /{" "}
              <code>pass_good</code>. Nothing here touches your real accounts.
            </>
          ) : (
            <>
              New transactions come from these banks instead of CSVs. Plaid checks your bank a
              few times a day, so a purchase can take a day to show up.
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-sm">
        {status && !status.configured ? (
          <p className="text-muted-foreground">{status.problem}</p>
        ) : (
          <>
            {items && current.length === 0 && (
              <p className="text-muted-foreground">No banks connected yet.</p>
            )}
            {current.map((item) => (
              <Bank
                key={item.id}
                item={item}
                result={results?.find((r) => r.item_id === item.id)}
                onReconnect={() => openLink(item.id)}
                onRemove={() => remove(item)}
                onLinked={sync}
                busy={busy !== null}
              />
            ))}
            {other.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-3">
                <p className="text-muted-foreground">
                  {item.institution_name} ({item.environment}, not used while PLAID_ENV is{" "}
                  {status?.environment})
                </p>
                <Button variant="ghost" size="sm" onClick={() => remove(item)}>
                  Disconnect
                </Button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              {current.length > 0 && (
                <Button onClick={sync} disabled={busy !== null}>
                  {busy === "sync" ? "Syncing…" : "Sync now"}
                </Button>
              )}
              <Button
                variant={current.length > 0 ? "outline" : "default"}
                onClick={() => openLink(null)}
                disabled={busy !== null || !status}
              >
                {busy === "connect" ? "Connecting…" : "Connect a bank"}
              </Button>
            </div>
          </>
        )}
        {(error ?? loadError) && <p className="text-destructive">{error ?? loadError}</p>}
        {link && (
          <PlaidLauncher
            token={link.token}
            onSuccess={linkFinished}
            onExit={(message) => {
              setLink(null);
              setBusy(null);
              if (message) setError(message);
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}

/** One connected bank: its sync status and which of my accounts each of its accounts is. */
function Bank({
  item,
  result,
  onReconnect,
  onRemove,
  onLinked,
  busy,
}: {
  item: PlaidItem;
  result: SyncResult | undefined;
  onReconnect: () => void;
  onRemove: () => void;
  onLinked: () => Promise<void>;
  busy: boolean;
}) {
  const needsLogin = item.status === "ITEM_LOGIN_REQUIRED";

  return (
    <section className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-medium">{item.institution_name}</h3>
          <p className="text-muted-foreground">
            {item.last_synced_at
              ? `Last synced ${timeAgo(item.last_synced_at)}`
              : `Connected ${formatDay(toIsoDate(new Date(item.created_at)))}, not synced yet`}
          </p>
        </div>
        <div className="flex gap-1">
          {needsLogin && (
            <Button size="sm" onClick={onReconnect} disabled={busy}>
              Reconnect
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onRemove} disabled={busy}>
            Disconnect
          </Button>
        </div>
      </div>

      {needsLogin ? (
        <p className="text-destructive">
          {item.institution_name} wants you to log in again before Plaid can read new
          transactions. Click Reconnect.
        </p>
      ) : (
        item.status !== "ok" && (
          <p className="text-destructive">The last sync failed ({item.status}).</p>
        )
      )}
      {result && <SyncSummary result={result} />}

      <BankAccounts item={item} onLinked={onLinked} />
    </section>
  );
}

function SyncSummary({ result: r }: { result: SyncResult }) {
  if (r.error) return <p className="text-destructive">Sync failed: {r.error}</p>;
  const parts = [
    `${r.added} new`,
    r.updated > 0 && `${r.updated} updated`,
    r.removed > 0 && `${r.removed} removed`,
    r.matched > 0 && `${r.matched} already imported from CSVs`,
  ].filter(Boolean);
  return <p role="status">Synced: {parts.join(", ")}.</p>;
}

/** Which of my accounts each account in this bank is. Saving starts a sync. */
function BankAccounts({ item, onLinked }: { item: PlaidItem; onLinked: () => Promise<void> }) {
  const { data: mine } = useApi<Account[]>("/accounts");
  const { data: theirs, error, reload } = useApi<PlaidAccount[]>(
    `/plaid/items/${item.id}/accounts`,
  );
  // My choice per Plaid account, while editing; starts from the saved link or the suggestion.
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  if (error) return <p className="text-destructive">{error}</p>;
  if (!theirs || !mine) return <p className="text-muted-foreground">Loading accounts…</p>;

  const saved = (pa: PlaidAccount) => (pa.account_id === null ? SKIP : String(pa.account_id));
  const choice = (pa: PlaidAccount) =>
    choices[pa.plaid_account_id] ??
    (pa.account_id ?? pa.suggested_account_id ?? SKIP).toString();
  const unsaved = theirs.some((pa) => choice(pa) !== saved(pa));
  const neverLinked = theirs.every((pa) => pa.account_id === null);

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      await api(`/plaid/items/${item.id}/accounts`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          links: theirs!.map((pa) => ({
            plaid_account_id: pa.plaid_account_id,
            account_id: choice(pa) === SKIP ? null : Number(choice(pa)),
          })),
        }),
      });
      setChoices({});
      reload();
      await onLinked();
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const options: Record<string, string> = {
    [SKIP]: "Don't import",
    ...Object.fromEntries(mine.map((a) => [String(a.id), a.name])),
  };

  return (
    <div className="flex flex-col gap-2">
      {neverLinked && (
        <p>
          Choose which of your accounts each one is. Transactions you already imported from
          CSVs are matched up, so nothing is added twice.
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {theirs.map((pa) => (
          <li key={pa.plaid_account_id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="min-w-48 flex-1">
              {pa.name}
              {pa.mask && <span className="text-muted-foreground"> ••{pa.mask}</span>}
            </span>
            <Select
              items={options}
              value={choice(pa)}
              onValueChange={(v) =>
                setChoices((c) => ({ ...c, [pa.plaid_account_id]: v as string }))
              }
            >
              <SelectTrigger className="w-56" aria-label={`Account for ${pa.name}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(options).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </li>
        ))}
      </ul>
      {unsaved && (
        <div>
          <Button size="sm" onClick={save} disabled={saving}>
            {saving ? "Saving…" : neverLinked ? "Save and sync" : "Save changes and sync"}
          </Button>
        </div>
      )}
      {saveError && <p className="text-destructive">{saveError}</p>}
    </div>
  );
}

/** Opens Plaid Link as soon as its script has loaded. Only rendered once we have a token. */
function PlaidLauncher({
  token,
  onSuccess,
  onExit,
}: {
  token: string;
  onSuccess: (publicToken: string, metadata: PlaidLinkOnSuccessMetadata) => void;
  onExit: (message: string | null) => void;
}) {
  const { open, ready } = usePlaidLink({
    token,
    onSuccess: (publicToken, metadata) => {
      if (publicToken) onSuccess(publicToken, metadata);
      else onExit("Plaid finished without connecting a bank. Try again.");
    },
    // Closing Link without finishing isn't an error; a failed login comes with a message.
    onExit: (err) => onExit(err ? (err.display_message ?? err.error_message) : null),
  });

  useEffect(() => {
    if (ready) open();
  }, [ready, open]);

  return null;
}
