// Grid A* over the hub floor (binary heap, 8 directions, no corner cutting),
// with line-of-sight smoothing so agents walk in natural straight lines.

class Heap {
  constructor() {
    this.items = [];
  }

  push(f, v) {
    const a = this.items;
    a.push([f, v]);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }

  pop() {
    const a = this.items;
    const top = a[0];
    const last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = i * 2 + 1;
        const r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }

  get size() {
    return this.items.length;
  }
}

export class NavGrid {
  constructor({ minX, maxX, minZ, maxZ, cell = 0.5 }) {
    Object.assign(this, { minX, maxX, minZ, maxZ, cell });
    this.cols = Math.ceil((maxX - minX) / cell);
    this.rows = Math.ceil((maxZ - minZ) / cell);
    this.blocked = new Uint8Array(this.cols * this.rows);
  }

  toCell(x, z) {
    return [
      Math.max(0, Math.min(this.cols - 1, Math.floor((x - this.minX) / this.cell))),
      Math.max(0, Math.min(this.rows - 1, Math.floor((z - this.minZ) / this.cell))),
    ];
  }

  toWorld(c, r) {
    return { x: this.minX + (c + 0.5) * this.cell, z: this.minZ + (r + 0.5) * this.cell };
  }

  block(x, z, w, d, margin = 0.25) {
    const [c0, r0] = this.toCell(x - w / 2 - margin, z - d / 2 - margin);
    const [c1, r1] = this.toCell(x + w / 2 + margin, z + d / 2 + margin);
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) this.blocked[r * this.cols + c] = 1;
  }

  blockCircle(x, z, radius) {
    const [c0, r0] = this.toCell(x - radius, z - radius);
    const [c1, r1] = this.toCell(x + radius, z + radius);
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const p = this.toWorld(c, r);
        if (Math.hypot(p.x - x, p.z - z) <= radius) this.blocked[r * this.cols + c] = 1;
      }
    }
  }

  free(c, r) {
    return c >= 0 && r >= 0 && c < this.cols && r < this.rows && !this.blocked[r * this.cols + c];
  }

  freeAt(x, z) {
    return this.free(...this.toCell(x, z));
  }

  nearestFree(c, r) {
    if (this.free(c, r)) return [c, r];
    for (let rad = 1; rad < 16; rad++) {
      for (let dr = -rad; dr <= rad; dr++) {
        for (let dc = -rad; dc <= rad; dc++) {
          if (Math.max(Math.abs(dr), Math.abs(dc)) !== rad) continue;
          if (this.free(c + dc, r + dr)) return [c + dc, r + dr];
        }
      }
    }
    return [c, r];
  }

  lineFree(a, b) {
    const dist = Math.hypot(b.x - a.x, b.z - a.z);
    const steps = Math.ceil(dist / (this.cell * 0.5));
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      if (!this.freeAt(a.x + (b.x - a.x) * t, a.z + (b.z - a.z) * t)) return false;
    }
    return true;
  }

  path(from, to) {
    const [sc, sr] = this.nearestFree(...this.toCell(from.x, from.z));
    const [gc, gr] = this.nearestFree(...this.toCell(to.x, to.z));
    const cols = this.cols;
    const start = sr * cols + sc;
    const goal = gr * cols + gc;
    const n = cols * this.rows;
    const g = new Float32Array(n).fill(Infinity);
    const came = new Int32Array(n).fill(-1);
    const closed = new Uint8Array(n);
    const open = new Heap();
    const h = (i) => {
      const dc = Math.abs((i % cols) - gc);
      const dr = Math.abs(Math.floor(i / cols) - gr);
      return dc + dr + (Math.SQRT2 - 2) * Math.min(dc, dr);
    };
    g[start] = 0;
    open.push(h(start), start);
    let found = false;
    while (open.size) {
      const [, cur] = open.pop();
      if (cur === goal) {
        found = true;
        break;
      }
      if (closed[cur]) continue;
      closed[cur] = 1;
      const cc = cur % cols;
      const cr = Math.floor(cur / cols);
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          if (!dr && !dc) continue;
          const nc = cc + dc;
          const nr = cr + dr;
          if (!this.free(nc, nr)) continue;
          if (dr && dc && (!this.free(cc + dc, cr) || !this.free(cc, cr + dr))) continue;
          const nb = nr * cols + nc;
          const cost = g[cur] + (dr && dc ? Math.SQRT2 : 1);
          if (cost < g[nb]) {
            g[nb] = cost;
            came[nb] = cur;
            open.push(cost + h(nb), nb);
          }
        }
      }
    }
    if (!found) return [{ x: to.x, z: to.z }];
    const cells = [];
    for (let i = goal; i !== -1; i = came[i]) cells.push(i);
    cells.reverse();
    const pts = cells.map((i) => this.toWorld(i % cols, Math.floor(i / cols)));
    pts[0] = { x: from.x, z: from.z };
    pts.push({ x: to.x, z: to.z });
    const smooth = [pts[0]];
    let anchor = 0;
    while (anchor < pts.length - 1) {
      let next = anchor + 1;
      while (next + 1 < pts.length && this.lineFree(pts[anchor], pts[next + 1])) next++;
      smooth.push(pts[next]);
      anchor = next;
    }
    return smooth.slice(1);
  }
}
