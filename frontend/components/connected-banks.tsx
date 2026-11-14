"use client";

import { useEffect, useState } from "react";
import { usePlaidLink, type PlaidLinkOnSuccessMetadata } from "react-plaid-link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, useApi, type PlaidItem, type PlaidStatus } from "@/lib/api";
import { formatDay, toIsoDate } from "@/lib/format";

/**
 * Banks connected through Plaid, and a button to connect another.
 *
 * Connecting: we ask our backend for a link token, which opens Plaid Link (Plaid's login
 * pop-up). You log in to your bank there, so your bank password only ever goes to Plaid.
 * Plaid Link then gives us a temporary public token, and the backend swaps it for the
 * permanent access token it keeps (encrypted) to read your transactions.
 */
export function ConnectedBanks() {
  const { data: status } = useApi<PlaidStatus>("/plaid/status");
  const { data: items, error: loadError, reload } = useApi<PlaidItem[]>("/plaid/items");
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startConnecting() {
    setBusy(true);
    setError(null);
    try {
      const { link_token } = await api<{ link_token: string }>("/plaid/link-token", {
        method: "POST",
      });
      setLinkToken(link_token); // PlaidLauncher opens Link once it has loaded
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function finishConnecting(publicToken: string, metadata: PlaidLinkOnSuccessMetadata) {
    setLinkToken(null);
    try {
      await api("/plaid/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          public_token: publicToken,
          institution_name: metadata.institution?.name ?? "Unknown bank",
        }),
      });
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(item: PlaidItem) {
    const sure = window.confirm(
      `Disconnect ${item.institution_name}? Plaid stops reading this bank. Transactions ` +
        "already imported stay.",
    );
    if (!sure) return;
    setError(null);
    try {
      await api(`/plaid/items/${item.id}`, { method: "DELETE" });
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const sandbox = status?.environment === "sandbox";

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
            "Banks Plaid reads transactions from, so you don't have to download CSVs."
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {status && !status.configured ? (
          <p className="text-muted-foreground">{status.problem}</p>
        ) : (
          <>
            {items && items.length === 0 && (
              <p className="text-muted-foreground">No banks connected yet.</p>
            )}
            {items && items.length > 0 && (
              <ul className="flex flex-col divide-y">
                {items.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-3 py-2">
                    <div>
                      <p className="font-medium">{item.institution_name}</p>
                      <p className="text-muted-foreground">
                        Connected {formatDay(toIsoDate(new Date(item.created_at)))}
                        {item.environment !== status?.environment && ` · ${item.environment}`}
                        {item.status !== "ok" && ` · needs attention (${item.status})`}
                      </p>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => remove(item)}>
                      Disconnect
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <div>
              <Button onClick={startConnecting} disabled={busy || !status}>
                {busy ? "Connecting…" : "Connect a bank"}
              </Button>
            </div>
          </>
        )}
        {(error ?? loadError) && <p className="text-destructive">{error ?? loadError}</p>}
        {linkToken && (
          <PlaidLauncher
            token={linkToken}
            onSuccess={finishConnecting}
            onExit={(message) => {
              setLinkToken(null);
              setBusy(false);
              if (message) setError(message);
            }}
          />
        )}
      </CardContent>
    </Card>
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
