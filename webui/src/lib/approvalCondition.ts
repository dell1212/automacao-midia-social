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
 * outside the two supported ones, a value that is not a list, or a list. Those
 * rules exist and the scheduler handles them. Returning null lets the screen
 * show them as they are rather than silently reinterpreting them.
 *
 * A present key with a ZERO-LENGTH list is one of those null cases, not an
 * absent key: `buildCondition` never emits one (an empty group is omitted
 * entirely), but the backend does no validation on `condition`, so a row like
 * `{"risk_level": []}` can already exist from the old free-form JSON
 * textarea. Reading it as "no risk filter" would be exactly backwards — Python's
 * `value not in []` is always true, so the rule matches NOTHING. The chips have
 * no way to express "this key is present but can never match", so this must
 * fall through to null rather than render a checked-nothing state as the
 * catch-all. */
export function readCondition(
  condition: Record<string, unknown>,
): { categories: string[]; risks: string[] } | null {
  for (const key of Object.keys(condition)) {
    if (!SUPPORTED_KEYS.includes(key)) return null;
    const value = condition[key];
    if (!Array.isArray(value) || value.length === 0) return null;
    if (value.some((item) => typeof item !== "string")) return null;
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
 * operator the wrong model of their own automation.
 *
 * For a condition the chips cannot represent, this says only that — it never
 * claims whether the rule matches or not. The backend's `in` check behaves
 * differently depending on the shape of the value (a list is membership, but
 * a plain string is SUBSTRING containment), so an unrepresentable condition
 * can still match some pieces, all of them, or none — there is no shape-
 * agnostic way to know from here, and asserting "nunca bate" was simply
 * wrong for the string case. */
/** Same sentence as `describeCondition`, from a result `readCondition`
 * already produced. Exists so a caller that already needed the parsed shape
 * (to pick a rendering branch, say) does not pay for a second `readCondition`
 * pass just to get the sentence — both wrap this one implementation, so the
 * wording stays in exactly one place either way. */
export function describeParsedCondition(
  parsed: { categories: string[]; risks: string[] } | null,
): string {
  if (!parsed) return "condição não reconhecida — a tela não sabe interpretá-la";

  const clauses: string[] = [];
  if (parsed.risks.length > 0) {
    const labels = parsed.risks.map((value) => RISK_LABEL.get(value) ?? value);
    clauses.push(`o risco for ${joinOr(labels)}`);
  }
  if (parsed.categories.length > 0) {
    const labels = parsed.categories.map((value) => CATEGORY_LABEL.get(value) ?? value);
    clauses.push(`a categoria for ${joinOr(labels)}`);
  }

  if (clauses.length === 0) return "para qualquer peça";
  if (clauses.length === 1) return `quando ${clauses[0]}`;
  // Joining both clauses with a bare " e " reads as precedence-ambiguous —
  // "quando o risco for Alto ou Médio e a categoria for Médico ou Jurídico"
  // can be parsed as (risco) AND (categoria), which is correct, or as
  // (Alto) OR (Médio AND Médico) OR (Jurídico), which is not. There are only
  // ever two clauses (SUPPORTED_KEYS has two entries), so spelling out "as
  // duas condições" and separating them with a semicolon — rather than
  // relying on "e" to both join clauses AND appear inside `joinOr`'s own
  // "ou" list — removes the ambiguity without turning the sentence into
  // pseudo-code.
  return `quando as duas condições a seguir são verdadeiras: ${clauses.join("; e ")}`;
}

export function describeCondition(condition: Record<string, unknown>): string {
  return describeParsedCondition(readCondition(condition));
}
