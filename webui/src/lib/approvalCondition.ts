/** Reading and writing an approval rule's `condition`.
 *
 * The semantics are the backend's, in `rule_matches`
 * (app/services/content/automation_scheduler.py:178-198):
 *
 *   - between fields: AND — every key present has to match
 *   - within a field: OR — the piece's value has to be in the list
 *   - empty condition: matches anything (the catch-all rule)
 *   - unknown key: never matches — a typo falls through to human review
 *     rather than silently matching everything
 *
 * The UI has to state all four correctly, which is why the sentence is built
 * here rather than assembled inline in the screen.
 */

export const CONTENT_CATEGORIES = [
  { value: "medical", label: "Médico" },
  { value: "pharmaceutical", label: "Farmacêutico" },
  { value: "financial", label: "Financeiro" },
  { value: "insurance", label: "Seguros" },
  { value: "legal", label: "Jurídico" },
  { value: "alcohol", label: "Álcool" },
  { value: "gambling", label: "Apostas" },
  { value: "political", label: "Político" },
  { value: "regulated_product", label: "Produto regulado" },
] as const;

export const RISK_LEVELS = [
  { value: "none", label: "Nenhum" },
  { value: "low", label: "Baixo" },
  { value: "medium", label: "Médio" },
  { value: "high", label: "Alto" },
] as const;

const SUPPORTED_KEYS = ["content_category", "risk_level"];

// Explicit <string, string>: without it, TS infers the Map's key type from
// the `as const` literals above, and then `.has`/`.get` reject the plain
// `string` values coming out of the free-form `condition` object.
const CATEGORY_LABEL = new Map<string, string>(
  CONTENT_CATEGORIES.map((item) => [item.value, item.label]),
);
const RISK_LABEL = new Map<string, string>(
  RISK_LEVELS.map((item) => [item.value, item.label]),
);

/** The chip selection a condition corresponds to, or null when the condition
 * cannot be represented by the chips.
 *
 * `condition` is free-form JSON on the backend, so a rule can carry a key
 * outside the two supported ones, or a value that is not a list. Those rules
 * exist and the scheduler handles them (they never match). Returning null lets
 * the screen show them as they are rather than silently reinterpreting them. */
export function readCondition(
  condition: Record<string, unknown>,
): { categories: string[]; risks: string[] } | null {
  for (const key of Object.keys(condition)) {
    if (!SUPPORTED_KEYS.includes(key)) return null;
    const value = condition[key];
    if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) return null;
  }
  const categories = (condition.content_category as string[] | undefined) ?? [];
  const risks = (condition.risk_level as string[] | undefined) ?? [];
  if (categories.some((value) => !CATEGORY_LABEL.has(value))) return null;
  if (risks.some((value) => !RISK_LABEL.has(value))) return null;
  return { categories, risks };
}

/** The condition for a chip selection.
 *
 * An empty group means the key does NOT go into the condition — not that it
 * matches an empty list, which would never match anything. Both groups empty
 * produces {}, the catch-all rule. */
export function buildCondition(
  categories: string[],
  risks: string[],
): Record<string, string[]> {
  const condition: Record<string, string[]> = {};
  if (categories.length > 0) condition.content_category = categories;
  if (risks.length > 0) condition.risk_level = risks;
  return condition;
}

function joinOr(labels: string[]): string {
  if (labels.length === 1) return labels[0];
  return `${labels.slice(0, -1).join(", ")} ou ${labels[labels.length - 1]}`;
}

/** The rule's condition as a sentence.
 *
 * "ou" inside a group and "e" between groups is not decoration — it is the
 * backend's matching rule, and getting it backwards in the UI would teach the
 * operator the wrong model of their own automation. */
export function describeCondition(condition: Record<string, unknown>): string {
  const parsed = readCondition(condition);
  if (!parsed) return "condição não reconhecida — esta regra nunca bate";

  const clauses: string[] = [];
  if (parsed.risks.length > 0) {
    const labels = parsed.risks.map((value) => RISK_LABEL.get(value) ?? value);
    clauses.push(`o risco for ${joinOr(labels).toLowerCase()}`);
  }
  if (parsed.categories.length > 0) {
    const labels = parsed.categories.map((value) => CATEGORY_LABEL.get(value) ?? value);
    clauses.push(`a categoria for ${joinOr(labels).toLowerCase()}`);
  }

  if (clauses.length === 0) return "para qualquer peça";
  return `quando ${clauses.join(" e ")}`;
}
