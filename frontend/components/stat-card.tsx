import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** One summary number, e.g. "Spent this month · $1,402", with an optional comparison line. */
export function StatCard({
  label,
  value,
  detail,
  detailTone = "muted",
}: {
  label: string;
  value: string | null; // null while loading
  detail?: React.ReactNode;
  detailTone?: "muted" | "positive" | "negative";
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        {value === null ? (
          <Skeleton className="h-8 w-28" />
        ) : (
          <div className="text-2xl font-semibold tracking-tight">{value}</div>
        )}
        {detail && (
          <div
            className={cn(
              "text-xs",
              detailTone === "muted" && "text-muted-foreground",
              detailTone === "positive" && "text-positive",
              detailTone === "negative" && "text-destructive",
            )}
          >
            {detail}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
