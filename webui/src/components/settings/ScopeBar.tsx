import { Card, MicroLabel } from "../ui/Card";
import { Select } from "./Controls";

export interface ScopeOption {
  id: number;
  label: string;
}

/** The client/campaign a screen is scoped to.
 *
 * Four screens show nothing until one is chosen. The choice used to be a bare
 * <select> floating above the list, and picking nothing left a blank page with
 * no explanation. Deliberately not persisted between visits: storing it would
 * raise the question of what to do when the stored record has since been
 * deactivated, for a convenience nobody asked for.
 */
export function ScopeBar({
  label,
  options,
  value,
  onChange,
  placeholder,
  isLoading,
}: {
  label: string;
  options: ScopeOption[] | undefined;
  value: number | null;
  onChange: (id: number | null) => void;
  placeholder: string;
  isLoading?: boolean;
}) {
  return (
    <Card className="flex flex-wrap items-center gap-3 px-4 py-3">
      <MicroLabel>{label}</MicroLabel>
      <div className="min-w-56">
        <Select
          value={value ?? ""}
          disabled={isLoading}
          aria-label={label}
          onChange={(event) => onChange(Number(event.target.value) || null)}
        >
          <option value="">{placeholder}</option>
          {options?.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>
    </Card>
  );
}
