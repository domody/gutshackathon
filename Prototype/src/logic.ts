export type Point = { x: number; y: number };

export const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

export function updatePinchState(
  current: boolean,
  normalizedDistance: number,
  engageThreshold: number,
  releaseThreshold: number,
): boolean {
  if (current) return normalizedDistance < releaseThreshold;
  return normalizedDistance < engageThreshold;
}

export function nearestSegmentDistance(point: Point, a: Point, b: Point): { distance: number; t: number } {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) return { distance: distance(point, a), t: 0 };
  const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared));
  return { distance: distance(point, { x: a.x + dx * t, y: a.y + dy * t }), t };
}

export function coverageIndex(point: Point, path: Point[], tolerance: number, bins: number): number | null {
  let bestDistance = Infinity;
  let bestProgress = 0;
  let traversed = 0;
  const lengths = path.slice(0, -1).map((p, i) => distance(p, path[i + 1]));
  const total = lengths.reduce((sum, n) => sum + n, 0);
  for (let i = 0; i < path.length - 1; i++) {
    const nearest = nearestSegmentDistance(point, path[i], path[i + 1]);
    if (nearest.distance < bestDistance) {
      bestDistance = nearest.distance;
      bestProgress = (traversed + lengths[i] * nearest.t) / total;
    }
    traversed += lengths[i];
  }
  return bestDistance <= tolerance ? Math.min(bins - 1, Math.floor(bestProgress * bins)) : null;
}

export function accumulateDamage(current: number, outside: boolean, carving: boolean, tracked: boolean, deltaSeconds: number, rate = 18): number {
  if (!outside || !carving || !tracked) return current;
  return Math.min(100, current + rate * Math.max(0, deltaSeconds));
}

export type SideStepState = { armed: boolean; choice: -1 | 0 | 1 };

export function updateSideStep(state: SideStepState, offset: number, threshold: number, centreZone = threshold * 0.45): SideStepState {
  if (!state.armed) return Math.abs(offset) <= centreZone ? { armed: true, choice: 0 } : { ...state, choice: 0 };
  if (offset <= -threshold) return { armed: false, choice: -1 };
  if (offset >= threshold) return { armed: false, choice: 1 };
  return { ...state, choice: 0 };
}

export function smooth(previous: Point | null, next: Point, amount: number): Point {
  if (!previous) return next;
  const keep = Math.max(0, Math.min(0.95, amount));
  return { x: previous.x * keep + next.x * (1 - keep), y: previous.y * keep + next.y * (1 - keep) };
}
