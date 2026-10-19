/** Read a theme token (e.g. "danger") at runtime, for places CSS classes cannot reach
 *  (SVG marker colours, canvas). The value still comes from the @theme block in index.css. */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim() || "currentColor";
}
