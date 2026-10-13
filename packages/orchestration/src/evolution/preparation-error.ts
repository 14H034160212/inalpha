/** Carry only non-secret input blocker codes across the approval middleware. */
export class EvolutionInputBlockedError extends Error {
  readonly code = "E2_INPUT_BLOCKED";
  readonly blocker_codes: string[];

  constructor(codes: string[]) {
    const blockers = codes.filter(code => /^[A-Z][A-Z0-9_]*$/.test(code));
    const normalized = blockers.length ? [...new Set(blockers)] : ["E2_INPUT_COVERAGE_INSUFFICIENT"];
    super(`E2_INPUT_BLOCKED: ${normalized.join(", ")}; inspect preparation; no generation started`);
    this.name = "EvolutionInputBlockedError";
    this.blocker_codes = normalized;
  }
}
