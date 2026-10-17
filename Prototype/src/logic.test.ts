import { describe, expect, it } from 'vitest';
import { accumulateDamage, coverageIndex, updatePinchState, updateSideStep } from './logic';

describe('tracing coverage', () => {
  const triangle = [{ x: 0, y: 1 }, { x: 0.5, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }];
  it('maps separated outline locations to separated bins', () => {
    expect(coverageIndex({ x: 0.25, y: 0.5 }, triangle, 0.05, 60)).not.toBe(
      coverageIndex({ x: 0.75, y: 0.5 }, triangle, 0.05, 60),
    );
  });
  it('rejects points outside the corridor', () => expect(coverageIndex({ x: 0.5, y: 0.6 }, triangle, 0.05, 60)).toBeNull());
});

describe('damage accumulation', () => {
  it('uses elapsed time and pauses on tracking loss', () => {
    expect(accumulateDamage(10, true, true, true, 0.5, 20)).toBe(20);
    expect(accumulateDamage(10, true, true, false, 1, 20)).toBe(10);
  });
});

describe('pinch hysteresis', () => {
  it('uses different engage and release thresholds', () => {
    expect(updatePinchState(false, 0.24, 0.25, 0.34)).toBe(true);
    expect(updatePinchState(true, 0.3, 0.25, 0.34)).toBe(true);
    expect(updatePinchState(true, 0.35, 0.25, 0.34)).toBe(false);
  });
});

describe('side-step rearming', () => {
  it('requires a centre return before another choice', () => {
    let state = updateSideStep({ armed: true, choice: 0 }, 0.2, 0.15);
    expect(state).toEqual({ armed: false, choice: 1 });
    state = updateSideStep(state, -0.2, 0.15);
    expect(state.choice).toBe(0);
    state = updateSideStep(state, 0.01, 0.15);
    expect(state.armed).toBe(true);
  });
});
