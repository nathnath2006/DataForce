/** First non-empty line, as the list title (Apple Notes style). */
export function noteTitle(body: string, max = 60): string {
  const line = body.split("\n").map((l) => l.trim()).find((l) => l !== "") ?? "";
  return line.length > max ? `${line.slice(0, max - 1)}…` : line || "Empty";
}

/** What follows the title, on one line, for the list preview. */
export function noteSnippet(body: string, max = 90): string {
  const lines = body.split("\n").map((l) => l.trim()).filter((l) => l !== "");
  const rest = lines.slice(1).join(" ");
  return rest.length > max ? `${rest.slice(0, max - 1)}…` : rest;
}
