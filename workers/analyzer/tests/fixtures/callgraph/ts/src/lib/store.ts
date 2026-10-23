export class Store {
  private items: string[] = []
  get(i: number) { return this.items[i] }
  put(x: string) { this.items.push(x); this.log() }
  log() {}
}

export class CachedStore extends Store {
  put(x: string) { super.put(x); this.get(0) }
}
