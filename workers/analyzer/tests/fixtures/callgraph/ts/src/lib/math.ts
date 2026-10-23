export function add(a: number, b: number) { return a + b }
export function double(n: number) { return add(n, n) }
export default function sum(xs: number[]) { return xs.reduce((a, b) => add(a, b), 0) }
