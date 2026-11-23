/** Wraps every page and is re-created on each navigation, so each page fades in gently. */
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex animate-in flex-col gap-4 duration-300 fade-in slide-in-from-bottom-1">
      {children}
    </div>
  );
}
