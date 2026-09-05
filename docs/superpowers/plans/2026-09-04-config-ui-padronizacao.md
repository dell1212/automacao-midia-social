# Padronização das telas de configuração — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trazer as 7 telas de `webui/src/pages/config/` para a linguagem visual do resto do app, com primitivas compartilhadas em vez de HTML cru repetido sete vezes.

**Architecture:** Um diretório novo `components/settings/` guarda a anatomia de uma tela de configuração (casca, escopo, tabela, ações de linha, painel lateral, controles de formulário). As 7 telas passam a montar essas peças em vez de escrever `<ul>`/`<form>` cru. A criação sai do fluxo vertical e vai para um `<dialog>` nativo aberto por uma ação primária no cabeçalho.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (sem Preflight), `@tanstack/react-query` v5, `react-router-dom` v7, `lucide-react`. Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-09-04-config-ui-padronizacao-design.md`

## Global Constraints

- **Nenhuma dependência nova.** O painel lateral usa `<dialog>` nativo; o projeto não tem Radix nem headless UI e não vai ganhar um.
- **Preflight do Tailwind está desligado** (`index.css:1-8`). O bloco `@layer base` (`index.css:147+`) estiliza `button`, `input`, `select`, `textarea`, `table`, `ul`, `h1` com seletores de tag crua. Utilitários vencem pela ordem de camadas, **mas cada propriedade que a regra base define precisa ser reafirmada** na versão nova, ou o valor antigo aparece por baixo. Ver o comentário em `Button.tsx:15-18`, que documenta essa armadilha já encontrada uma vez.
- **Não remover o bloco `@layer base`.** `PieceQueue`, `PieceDetail`, `History` e `AuditLogList` ainda dependem dele.
- **Não mexer em `RequireRole`.** Toda checagem de permissão fica exatamente onde está.
- **Não mexer no `AppShell`** (menu lateral) — pedido explícito do autor.
- **Sem suíte de testes.** O `webui` não tem `vitest` nem script `test`. A política do projeto (ver handoff `2026-08-30-webui-ux-config-backlog.md`) é verificar com `tsc -b && vite build` limpo + `oxlint` e validação visual no navegador. **Não introduzir suíte de testes neste plano.**
- **`oxlint` tem 9 warnings pré-existentes** — medidos nesta base, não estimados: `PlatformIcon.tsx` (3), `SessionProvider.tsx` (2), `Charts.tsx` (1), `CaptionEditor.tsx` (1), `AuditLogList.tsx` (1), `Composer.tsx` (1). Todos são `react(only-export-components)` ou `react(set-state-in-effect)`. São a linha de base: nenhuma task pode adicionar warnings novos, e nenhuma precisa corrigir estes.
- **Textos de interface em português**, com acentuação correta. Código, nomes de componentes, props e comentários em inglês.
- **`Field` renderiza um `<label>` que envolve o controle**, e `<label>` só aceita phrasing content. Dentro de um `Field`, usar `<span className="block">` ou `<span className="flex">` onde normalmente se usaria `<div>`. Para um **grupo** de controles (chips, radios), `Field` é a ferramenta errada — usar `<fieldset>`/`<legend>`, como o `ChipGroup` da Task 13 faz.
- **Endpoints: copiar do arquivo que está sendo reescrito, nunca de memória.** Dois casos não seguem o padrão REST que o resto sugere, e "corrigi-los" quebra a tela:
  - `ApprovalRules` — **lê** em `GET /content/ui/config/campaigns/{id}/approval-rules`, mas **cria** em `POST /content/ui/config/approval-rules` com `campaign_id` no corpo.
  - `Avatars` — cria com `apiClient.uploadFile(...)`, não `apiClient.post(...)`; é um método distinto do cliente, para `FormData`.
- **Tema claro e escuro.** Cores sempre via token (`var(--card-bg)`, `var(--border)`, `var(--text)`, `var(--text-h)`, `var(--code-bg)`) ou classe de tema (`bg-lime`, `text-ink`, `bg-bad`). Nunca hex literal.
- **Enums do backend, valores exatos:**
  - `ContentCategory`: `medical`, `pharmaceutical`, `financial`, `insurance`, `legal`, `alcohol`, `gambling`, `political`, `regulated_product`
  - `RiskLevel`: `none`, `low`, `medium`, `high`
  - `Campaign.status`: `active` | `archived`
  - `SocialAccount.status`: `active` | `revoked`
  - `Provider.kind`: `image` | `video` | `voice`; `Provider.provider`: `wavespeed` | `falai` | `gemini` | `elevenlabs`

## Ciclo de verificação (toda task)

Substitui o ciclo de TDD, que não se aplica aqui — não há suíte para escrever teste dentro.

```bash
cd webui
npm run build     # tsc -b && vite build — precisa terminar sem erro
npm run lint      # oxlint — só os 3 warnings pré-existentes
```

Tasks que tocam tela adicionam validação no navegador. Para subir o ambiente local (backend + token de sessão), seguir o handoff `docs/superpowers/handoffs/2026-08-30-webui-ux-config-backlog.md` — ele tem os comandos exatos. **Não copiar as credenciais dele para lugar nenhum.**

**Alinhamento se verifica medindo.** Onde a task pedir conferência de layout, usar `getBoundingClientRect` via Playwright e comparar números — screenshot não basta. Essa disciplina já custou uma rodada de retrabalho neste projeto.

---

## File Structure

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `webui/src/components/settings/Field.tsx` | `Field` — label + controle + hint + erro |
| `webui/src/components/settings/Controls.tsx` | `Input`, `Select`, `Textarea` |
| `webui/src/components/settings/EntityChip.tsx` | `EntityChip`, `EntityState` |
| `webui/src/components/settings/DataTable.tsx` | `DataTable`, `Column<T>` |
| `webui/src/components/settings/RowActions.tsx` | `RowActions`, `RowAction` |
| `webui/src/components/settings/Drawer.tsx` | `Drawer` |
| `webui/src/components/settings/SettingsPage.tsx` | `SettingsPage` |
| `webui/src/components/settings/ScopeBar.tsx` | `ScopeBar`, `ScopeOption` |
| `webui/src/lib/approvalCondition.ts` | Leitura/escrita/descrição da condição de regra |

**Modificar:** as 7 telas em `webui/src/pages/config/`.

**Não tocar:** `AppShell.tsx`, `App.tsx`, `components/ui/*`, `RequireRole.tsx`, qualquer arquivo do backend.

**`index.css` — regra especial:** o bloco `@layer base` existente e tudo acima dele são intocáveis. A Task 5 **acrescenta** as regras de `.settings-drawer` ao fim do arquivo, depois desse bloco; é a única alteração autorizada neste arquivo em todo o plano.

### Vazamentos do `@layer base` já medidos — não reintroduzir

Cada um destes custou uma rodada de correção. As classes que os neutralizam já estão no código de cada task; não as remova por parecerem redundantes.

| Regra base | Onde vaza | Neutralizador |
|---|---|---|
| `form { align-items: flex-end; flex-wrap: wrap; margin: 4px 0 16px }` (`index.css:347`) | Todo `<form>` dos drawers. Com `flex-col`, `align-items: flex-end` encolhe cada campo e o cola na borda direita — medido: input com 167px de 386px disponíveis | `items-stretch flex-nowrap m-0` |
| `button + button { margin-left: 8px }` (`index.css:282`), zerada só para `nav` | Todo par `[Ação] [Cancelar]`. Flex **soma** a margem ao `gap`, não a ignora — medido: 14px onde o `gap` declara 6px | `[&>button+button]:ml-0` no container |
| `table { margin: 0 0 16px }` (`index.css:395`) | `DataTable` | `m-0` (já aplicado) |
| `th, td { border-bottom }` (`index.css:403`) | Última linha da tabela | `[&:last-child>td]:border-b-0` no `<tr>` (já aplicado) |
| `button { border-radius: var(--radius) }` | Itens do menu de `RowActions` | `rounded-none` (já aplicado) |

O comentário em `index.css:276` afirma que a margem entre botões é "ignored inside nav/forms, which are flex". **É falso** — foi medido. Não confie nele.

**Estado do drawer ao fechar.** Fechar por `Esc`, backdrop ou "Cancelar" precisa limpar os campos e chamar `<mutation>.reset()`. Sem isso, reabrir o painel mostra o que foi digitado antes e o erro da tentativa anterior, como se fossem novos.

---

## Task 1: Controles de formulário e Field

**Files:**
- Create: `webui/src/components/settings/Controls.tsx`
- Create: `webui/src/components/settings/Field.tsx`

**Interfaces:**
- Consumes: `cn` de `components/ui/cn`
- Produces:
  - `Input(props: InputHTMLAttributes<HTMLInputElement>): JSX.Element`
  - `Select(props: SelectHTMLAttributes<HTMLSelectElement>): JSX.Element`
  - `Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>): JSX.Element`
  - `Field({ label, hint, error, children }: { label: string; hint?: string; error?: string | null; children: ReactNode }): JSX.Element`

- [ ] **Step 1: Ler a regra base que estes controles precisam vencer**

Abrir `webui/src/index.css` e localizar, dentro de `@layer base`, as regras para `input`, `select`, `textarea`. Anotar toda propriedade que elas definem (altura, padding, borda, background, cor, fonte, raio). Cada uma tem que ser reafirmada no passo seguinte — é exatamente a armadilha documentada em `Button.tsx:15-18`.

- [ ] **Step 2: Escrever `Controls.tsx`**

```tsx
import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { cn } from "../ui/cn";

// Preflight is off, so the `base` layer still styles bare input/select/
// textarea for the not-yet-migrated screens. Utilities outrank it by layer
// order, but only for properties they actually set — every property the base
// rule defines has to be restated here or the old value shows through. Same
// trap `Button.tsx` documents.
const CONTROL =
  "w-full h-8 px-2.5 text-[13px] font-normal font-sans " +
  "text-[var(--text-h)] bg-[var(--card-bg)] " +
  "border border-[var(--border)] rounded-[4px] " +
  "outline-none transition-colors " +
  "focus:border-[var(--accent-border)] focus:ring-2 focus:ring-[var(--ring)] " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "placeholder:text-[var(--text)]";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, className)} {...rest} />;
}

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  // `appearance-none` plus an explicit chevron: the native arrow ignores the
  // dark theme in Chromium and renders on a light plate.
  //
  // The wrapper is a <span class="block">, not a <div>: this renders inside
  // Field's <label>, which only accepts phrasing content.
  return (
    <span className="relative block">
      <select
        className={cn(CONTROL, "appearance-none pr-8 cursor-pointer", className)}
        {...rest}
      />
      <svg
        aria-hidden
        viewBox="0 0 12 12"
        className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-[var(--text)]"
      >
        <path d="M2 4.5 6 8.5 10 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </span>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, "h-auto min-h-20 py-2 leading-relaxed", className)} {...rest} />;
}
```

- [ ] **Step 3: Escrever `Field.tsx`**

```tsx
import type { ReactNode } from "react";

/** Label + control + hint + error, in one shape for every settings form.
 *
 * The <label> wraps the control rather than pointing at it by id: the
 * association is implicit, so callers write <Field label="X"><Input /></Field>
 * with no id to thread through and nothing to keep in sync.
 *
 * Several screens used placeholder-as-label, which disappears the moment
 * someone types and leaves a half-filled form unreadable. That is what this
 * replaces.
 *
 * For a GROUP of controls (a set of chips, a radio group) a wrapping label is
 * wrong — one label cannot name several controls. Use <fieldset>/<legend>
 * instead, as the chip groups on the approval rules screen do.
 */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      {/* Spans, not <p>: only phrasing content is valid inside a <label>. */}
      <span className="text-[13px] font-medium text-[var(--text-h)]">{label}</span>
      {children}
      {hint ? <span className="text-[12px] text-[var(--text)]">{hint}</span> : null}
      {error ? <span className="text-[12px] text-bad">{error}</span> : null}
    </label>
  );
}
```

- [ ] **Step 4: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

Esperado: build sem erro; `oxlint` com os 3 warnings pré-existentes e nenhum novo.

- [ ] **Step 5: Commit**

```bash
git add webui/src/components/settings/Controls.tsx webui/src/components/settings/Field.tsx
git commit -m "feat(webui): form control primitives for the settings screens"
```

---

## Task 2: EntityChip

**Files:**
- Create: `webui/src/components/settings/EntityChip.tsx`

**Interfaces:**
- Consumes: `cn` de `components/ui/cn`
- Produces:
  - `type EntityState = "active" | "inactive" | "archived" | "revoked"`
  - `EntityChip({ state, className }: { state: EntityState; className?: string }): JSX.Element`

- [ ] **Step 1: Escrever `EntityChip.tsx`**

```tsx
import { cn } from "../ui/cn";

/** Lifecycle of a configuration record.
 *
 * Deliberately separate from `ui/StatusChip`, which is the lifecycle of a
 * content piece (draft → generating → posted). The two vocabularies change
 * for different reasons and merging them would couple two independent
 * evolutions. The look is identical on purpose: the distinction is ours, not
 * the reader's.
 */
export type EntityState = "active" | "inactive" | "archived" | "revoked";

const STYLES: Record<EntityState, { label: string; className: string }> = {
  active: { label: "Ativo", className: "bg-ok/15 text-ok" },
  inactive: { label: "Inativo", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  archived: { label: "Arquivada", className: "bg-[var(--code-bg)] text-[var(--text)]" },
  revoked: { label: "Revogada", className: "bg-bad/15 text-bad" },
};

export function EntityChip({
  state,
  className,
}: {
  state: EntityState;
  className?: string;
}) {
  const style = STYLES[state];
  // `Campaign.status` and `SocialAccount.status` are plain strings on the
  // backend, so an unmapped value can arrive. Show it rather than render an
  // empty chip.
  if (!style) {
    return (
      <span
        className={cn(
          "inline-flex items-center h-5 px-2 rounded-full text-[11px] font-medium",
          "bg-[var(--code-bg)] text-[var(--text)]",
          className,
        )}
      >
        {state}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center h-5 px-2 rounded-full text-[11px] font-medium whitespace-nowrap",
        style.className,
        className,
      )}
    >
      {style.label}
    </span>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

Esperado: build sem erro, sem warning novo.

- [ ] **Step 3: Commit**

```bash
git add webui/src/components/settings/EntityChip.tsx
git commit -m "feat(webui): entity lifecycle chip for the settings screens"
```

---

## Task 3: DataTable

**Files:**
- Create: `webui/src/components/settings/DataTable.tsx`

**Interfaces:**
- Consumes: `Card` de `components/ui/Card`, `SkeletonRows`/`EmptyState` de `components/ui/Feedback`, `cn`
- Produces:
  - `interface Column<T> { key: string; header: string; align?: "left" | "right"; width?: string; render: (row: T) => ReactNode }`
  - `DataTable<T>({ columns, rows, rowKey, isLoading, isError, emptyTitle, emptyHint }): JSX.Element`

- [ ] **Step 1: Escrever `DataTable.tsx`**

```tsx
import type { ReactNode } from "react";
import { Card } from "../ui/Card";
import { EmptyState, SkeletonRows } from "../ui/Feedback";
import { cn } from "../ui/cn";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  /** Any CSS width. Left undefined the column takes its share of the rest. */
  width?: string;
  render: (row: T) => ReactNode;
}

/** The list half of every settings screen.
 *
 * Loading, error and empty live in here rather than in each screen: the seven
 * screens each spelled those three states out by hand, in slightly different
 * words, and the empty case was a blank page with no explanation at all.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  isLoading,
  isError,
  emptyTitle,
  emptyHint,
}: {
  columns: Array<Column<T>>;
  rows: T[] | undefined;
  rowKey: (row: T) => string | number;
  isLoading?: boolean;
  isError?: boolean;
  emptyTitle: string;
  emptyHint?: string;
}) {
  if (isLoading) {
    return (
      <Card className="p-4">
        <SkeletonRows rows={5} />
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <EmptyState
          title="Não foi possível carregar"
          hint="Verifique a conexão com o servidor e tente novamente."
        />
      </Card>
    );
  }

  if (!rows || rows.length === 0) {
    return (
      <Card>
        <EmptyState title={emptyTitle} hint={emptyHint} action={emptyAction} />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      {/* The wrapper scrolls, not the page: a five-column table must not make
          the whole layout scroll sideways on a narrow viewport. */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              {columns.map((column) => (
                <th
                  key={column.key}
                  style={column.width ? { width: column.width } : undefined}
                  className={cn(
                    "px-4 py-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.12em]",
                    "text-[var(--text)] whitespace-nowrap",
                    column.align === "right" ? "text-right" : "text-left",
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--code-bg)] transition-colors"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      "px-4 py-2.5 text-[var(--text-h)] align-middle",
                      column.align === "right" ? "text-right" : "text-left",
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Commit**

```bash
git add webui/src/components/settings/DataTable.tsx
git commit -m "feat(webui): data table with built-in loading, error and empty states"
```

---

## Task 4: RowActions

**Files:**
- Create: `webui/src/components/settings/RowActions.tsx`

**Interfaces:**
- Consumes: `Button` de `components/ui/Button`, `cn`; ícone `MoreHorizontal` de `lucide-react`
- Produces:
  - `interface RowAction { label: string; onConfirm: () => void; disabled?: boolean; danger?: boolean; confirmLabel?: string }`
  - `RowActions({ actions, pending }: { actions: RowAction[]; pending?: boolean }): JSX.Element | null`

- [ ] **Step 1: Escrever `RowActions.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "../ui/Button";
import { cn } from "../ui/cn";

export interface RowAction {
  label: string;
  onConfirm: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Defaults to the action's own label. */
  confirmLabel?: string;
}

/** Trailing action menu for a table row.
 *
 * Destructive actions used to fire on the first click — "Desativar"
 * deactivated, no question asked. Confirmation is inline, in the row itself,
 * rather than a modal: every action here is a logical deactivation, not a
 * DELETE of data, and a full-screen interruption would outweigh it.
 */
export function RowActions({
  actions,
  pending,
}: {
  actions: RowAction[];
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setConfirming(null);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        setConfirming(null);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const enabled = actions.filter((action) => !action.disabled);
  if (enabled.length === 0) return null;

  const active = confirming
    ? enabled.find((action) => action.label === confirming)
    : undefined;

  if (active) {
    return (
      <div className="inline-flex items-center gap-1.5 justify-end">
        <span className="text-[12px] text-[var(--text)]">Confirmar?</span>
        <Button
          size="sm"
          variant={active.danger ? "danger" : "primary"}
          disabled={pending}
          onClick={() => {
            active.onConfirm();
            setConfirming(null);
            setOpen(false);
          }}
        >
          {active.confirmLabel ?? active.label}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
          Cancelar
        </Button>
      </div>
    );
  }

  return (
    <div ref={rootRef} className="relative inline-flex justify-end">
      <Button
        size="sm"
        variant="ghost"
        aria-label="Ações"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={pending}
        onClick={() => setOpen((value) => !value)}
        className="px-1.5"
      >
        <MoreHorizontal size={15} />
      </Button>
      {open ? (
        <div
          role="menu"
          className={cn(
            "absolute right-0 top-full z-20 mt-1 min-w-40 py-1",
            "bg-[var(--card-bg)] border border-[var(--border)] rounded-[4px]",
            "shadow-[0_4px_16px_rgba(0,0,0,0.12)]",
          )}
        >
          {enabled.map((action) => (
            <button
              key={action.label}
              type="button"
              role="menuitem"
              onClick={() => setConfirming(action.label)}
              className={cn(
                "block w-full h-8 px-3 text-left text-[13px] font-medium",
                "bg-transparent border-0 cursor-pointer transition-colors",
                "hover:bg-[var(--code-bg)]",
                action.danger ? "text-bad" : "text-[var(--text-h)]",
              )}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Commit**

```bash
git add webui/src/components/settings/RowActions.tsx
git commit -m "feat(webui): row action menu with inline confirmation"
```

---

## Task 5: Drawer

**Files:**
- Create: `webui/src/components/settings/Drawer.tsx`

**Interfaces:**
- Consumes: `Button`, `cn`; ícone `X` de `lucide-react`
- Produces:
  - `Drawer({ open, onClose, title, description, children }: { open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode }): JSX.Element`

- [ ] **Step 1: Escrever `Drawer.tsx`**

```tsx
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "../ui/Button";

/** Side panel for creating a record.
 *
 * Native <dialog> with showModal(), not a div with a backdrop: it gives focus
 * trapping, Esc to close, inerting the page behind, and returning focus to the
 * trigger — all of which we would otherwise have to write and get wrong.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // Esc closes the dialog natively; this keeps React's state in step with
    // what the DOM already did.
    function onCancel(event: Event) {
      event.preventDefault();
      onClose();
    }
    dialog.addEventListener("cancel", onCancel);
    return () => dialog.removeEventListener("cancel", onCancel);
  }, [onClose]);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      onClick={(event) => {
        // The backdrop is the dialog element itself: a click whose target is
        // the dialog (not a child) landed outside the panel.
        if (event.target === ref.current) onClose();
      }}
      className={
        "settings-drawer m-0 ml-auto h-svh max-h-svh w-full max-w-[min(26rem,100vw)] " +
        "p-0 border-0 bg-transparent"
      }
    >
      <div className="flex h-full flex-col border-l border-[var(--border)] bg-[var(--card-bg)]">
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0">
            <h2 className="m-0 text-[15px] font-semibold tracking-tight text-[var(--text-h)]">
              {title}
            </h2>
            {description ? (
              <p className="m-0 mt-1 text-[12px] text-[var(--text)]">{description}</p>
            ) : null}
          </div>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Fechar"
            onClick={onClose}
            className="px-1.5 shrink-0"
          >
            <X size={15} />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </dialog>
  );
}
```

- [ ] **Step 2: Adicionar o estilo do backdrop e da entrada**

`::backdrop` não herda variáveis CSS do documento em todos os motores, então a cor precisa ser declarada nele. Acrescentar ao **fim** de `webui/src/index.css`, fora do bloco `@layer base` (não mexer no que já está lá):

```css
/* The drawer's backdrop and slide-in. `::backdrop` sits outside the document
   tree in some engines and does not inherit custom properties, so its colour
   is spelled out here for each theme instead of using a token. */
.settings-drawer::backdrop {
  background: rgba(20, 20, 19, 0.4);
}

@media (prefers-color-scheme: dark) {
  .settings-drawer::backdrop {
    background: rgba(0, 0, 0, 0.6);
  }
}

.settings-drawer[open] {
  animation: settings-drawer-in 0.18s ease-out;
}

@keyframes settings-drawer-in {
  from {
    transform: translateX(1.5rem);
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .settings-drawer[open] {
    animation: none;
  }
}
```

- [ ] **Step 3: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/components/settings/Drawer.tsx webui/src/index.css
git commit -m "feat(webui): side drawer built on the native dialog element"
```

---

## Task 6: SettingsPage e ScopeBar

**Files:**
- Create: `webui/src/components/settings/SettingsPage.tsx`
- Create: `webui/src/components/settings/ScopeBar.tsx`

**Interfaces:**
- Consumes: `Card`/`MicroLabel` de `components/ui/Card`, `Select` de `settings/Controls`
- Produces:
  - `SettingsPage({ title, description, action, children }: { title: string; description?: string; action?: ReactNode; children: ReactNode }): JSX.Element`
  - `interface ScopeOption { id: number; label: string }`
  - `ScopeBar({ label, options, value, onChange, placeholder, isLoading }: { label: string; options: ScopeOption[] | undefined; value: number | null; onChange: (id: number | null) => void; placeholder: string; isLoading?: boolean }): JSX.Element`

- [ ] **Step 1: Escrever `SettingsPage.tsx`**

```tsx
import type { ReactNode } from "react";

/** Outer frame every settings screen shares: title, one line saying what the
 * screen controls, and the slot for the primary action. */
export function SettingsPage({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="m-0 text-[20px] font-semibold tracking-tight text-[var(--text-h)]">
            {title}
          </h1>
          {description ? (
            <p className="m-0 mt-1 max-w-2xl text-[13px] text-[var(--text)]">{description}</p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Escrever `ScopeBar.tsx`**

```tsx
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
```

- [ ] **Step 3: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/components/settings/SettingsPage.tsx webui/src/components/settings/ScopeBar.tsx
git commit -m "feat(webui): settings page frame and scope bar"
```

---

## Task 7: Tela piloto — Clientes

Primeira tela a montar as primitivas todas juntas. Se o padrão estiver errado, é aqui que aparece — antes de repetir seis vezes.

**Files:**
- Modify: `webui/src/pages/config/Clients.tsx` (arquivo inteiro, 79 linhas hoje)

**Interfaces:**
- Consumes: `SettingsPage`, `DataTable`/`Column`, `RowActions`, `Drawer`, `Field`, `Input`, `EntityChip`, `Button`
- Produces: nada para tasks seguintes — é uma tela

- [ ] **Step 1: Reescrever `Clients.tsx`**

Preservar exatamente: as queries (`["config", "clients"]`), as mutations, os endpoints, e os dois `RequireRole role="admin"` (um envolvendo a ação de criar, outro a ação de desativar).

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient, apiErrorStatus } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Client, ClientPayload } from "../../lib/types";

export function Clients() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [name, setName] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const create = useMutation({
    mutationFn: (payload: ClientPayload) =>
      apiClient.post<Client>("/content/ui/config/clients", payload),
    onSuccess: () => {
      setName("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "clients"] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Client>(`/content/ui/config/clients/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "clients"] }),
  });

  const forbidden = apiErrorStatus(create.error) === 403;

  const columns: Array<Column<Client>> = [
    {
      key: "name",
      header: "Nome",
      render: (client) => <span className="font-medium">{client.name}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (client) => <EntityChip state={client.is_active ? "active" : "inactive"} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (client) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={deactivate.isPending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !client.is_active,
                onConfirm: () => deactivate.mutate(client.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Clientes"
      description="Cada cliente agrupa suas próprias campanhas, contas sociais e avatares."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button variant="primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={15} />
            Novo cliente
          </Button>
        </RequireRole>
      }
    >
      <DataTable
        columns={columns}
        rows={clients.data}
        rowKey={(client) => client.id}
        isLoading={clients.isLoading}
        isError={clients.isError}
        emptyTitle="Nenhum cliente cadastrado"
        emptyHint="Crie o primeiro cliente para começar a montar campanhas."
      />

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Novo cliente"
        description="O nome pode ser alterado depois pelo suporte."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ name });
          }}
        >
          <Field
            label="Nome"
            error={forbidden ? "Você não tem permissão para criar clientes." : null}
          >
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome do cliente"
              required
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button type="submit" variant="primary" disabled={create.isPending || !name.trim()}>
              {create.isPending ? "Criando…" : "Criar cliente"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Validar no navegador**

Subir backend e webui conforme o handoff `docs/superpowers/handoffs/2026-08-30-webui-ux-config-backlog.md`, abrir `/config/clients` e conferir:

1. A tabela lista os clientes com chip de status.
2. "Novo cliente" abre o drawer; `Esc` fecha; clique no backdrop fecha.
3. Com o drawer aberto, `Tab` circula apenas dentro do painel.
4. Ao fechar, o foco volta ao botão "Novo cliente".
5. Criar um cliente fecha o drawer e a linha nova aparece.
6. "Desativar" pede "Confirmar?" antes de agir.
7. Alternar o tema do sistema para escuro: backdrop, tabela e drawer legíveis.

Medir com Playwright, não olhar screenshot:

```js
// Cabeçalho e primeira célula têm que partir da mesma borda esquerda.
const th = document.querySelector('table thead th').getBoundingClientRect();
const td = document.querySelector('table tbody td').getBoundingClientRect();
console.log({ th: th.left, td: td.left, diff: Math.abs(th.left - td.left) });
// Esperado: diff === 0
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/Clients.tsx
git commit -m "feat(webui): rebuild the clients screen on the settings primitives"
```

---

## Task 8: Campanhas

**Files:**
- Modify: `webui/src/pages/config/Campaigns.tsx` (arquivo inteiro, 114 linhas hoje)

**Interfaces:**
- Consumes: as mesmas primitivas da Task 7, mais `Select`
- Produces: nada para tasks seguintes

- [ ] **Step 1: Reescrever `Campaigns.tsx`**

Novidade em relação à Task 7: a coluna **Cliente**, que hoje não existe. A tela lista campanhas de todos os clientes misturadas sem dizer de quem é cada uma. A query `["config", "clients"]` já é feita para o formulário, então é reuso — não uma requisição a mais.

Preservar: queries, mutations, endpoints e o `RequireRole`.

```tsx
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip, type EntityState } from "../../components/settings/EntityChip";
import type { Campaign, Client } from "../../lib/types";

export function Campaigns() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [horizonDays, setHorizonDays] = useState(7);

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<Campaign>("/content/ui/config/campaigns", {
        client_id: clientId,
        name,
        horizon_days: horizonDays,
      }),
    onSuccess: () => {
      setName("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] });
    },
  });

  const archive = useMutation({
    mutationFn: (id: number) => apiClient.delete<Campaign>(`/content/ui/config/campaigns/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] }),
  });

  // Name by id, so the new column does not cost a request per row.
  const clientName = useMemo(() => {
    const map = new Map<number, string>();
    clients.data?.forEach((client) => map.set(client.id, client.name));
    return map;
  }, [clients.data]);

  const columns: Array<Column<Campaign>> = [
    {
      key: "name",
      header: "Nome",
      render: (campaign) => <span className="font-medium">{campaign.name}</span>,
    },
    {
      key: "client",
      header: "Cliente",
      render: (campaign) => clientName.get(campaign.client_id) ?? "—",
    },
    {
      key: "horizon",
      header: "Horizonte",
      align: "right",
      width: "9rem",
      render: (campaign) => (
        <span className="font-mono text-[12px]">{campaign.horizon_days} dias</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (campaign) => <EntityChip state={campaign.status as EntityState} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (campaign) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={archive.isPending}
            actions={[
              {
                label: "Arquivar",
                danger: true,
                disabled: campaign.status !== "active",
                onConfirm: () => archive.mutate(campaign.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Campanhas"
      description="Uma campanha define o que é gerado, com que antecedência e sob quais regras de aprovação."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button variant="primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={15} />
            Nova campanha
          </Button>
        </RequireRole>
      }
    >
      <DataTable
        columns={columns}
        rows={campaigns.data}
        rowKey={(campaign) => campaign.id}
        isLoading={campaigns.isLoading}
        isError={campaigns.isError}
        emptyTitle="Nenhuma campanha cadastrada"
        emptyHint="Crie uma campanha para que a automação comece a gerar conteúdo."
      />

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Nova campanha"
        description="O horizonte define quantos dias à frente a automação gera conteúdo."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId !== null) create.mutate();
          }}
        >
          <Field label="Cliente">
            <Select
              value={clientId ?? ""}
              onChange={(event) => setClientId(Number(event.target.value) || null)}
              required
            >
              <option value="">Selecione um cliente</option>
              {clients.data?.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Nome da campanha">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome da campanha"
              required
            />
          </Field>
          <Field
            label="Horizonte de geração"
            hint="Quantos dias à frente a automação gera conteúdo para esta campanha."
          >
            <Input
              type="number"
              min={1}
              value={horizonDays}
              onChange={(event) => setHorizonDays(Number(event.target.value))}
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || clientId === null || !name.trim()}
            >
              {create.isPending ? "Criando…" : "Criar campanha"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Validar no navegador**

Em `/config/campaigns`: a coluna Cliente mostra o nome (não o id); campanhas de clientes diferentes ficam distinguíveis; criar funciona; "Arquivar" pede confirmação e fica desabilitado em campanha já arquivada.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/Campaigns.tsx
git commit -m "feat(webui): rebuild the campaigns screen, showing which client each belongs to"
```

---

## Task 9: Provedores

**Files:**
- Modify: `webui/src/pages/config/Providers.tsx` (arquivo inteiro, 130 linhas hoje)

**Interfaces:**
- Consumes: as primitivas das tasks 1-6
- Produces: nada para tasks seguintes

- [ ] **Step 1: Reescrever `Providers.tsx`**

Novidade: a prioridade editável na célula fica (é útil), mas hoje dispara no `onBlur` sem retorno visual — não dá para saber se salvou. Passa a mostrar "salvando…", depois "salvo", e a reverter o campo se a mutation falhar.

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient, apiErrorStatus } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Provider, ProviderCreatePayload } from "../../lib/types";

const KIND_LABEL: Record<Provider["kind"], string> = {
  image: "Imagem",
  video: "Vídeo",
  voice: "Voz",
};

const PROVIDER_LABEL: Record<Provider["provider"], string> = {
  wavespeed: "Wavespeed",
  falai: "fal.ai",
  gemini: "Gemini",
  elevenlabs: "ElevenLabs",
};

/** Priority cell: editable in place, but saying what it did.
 *
 * The old cell fired the mutation on blur and showed nothing at all, so a
 * failed save was indistinguishable from a successful one.
 */
function PriorityCell({ provider }: { provider: Provider }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(provider.priority));
  const [saved, setSaved] = useState(false);

  const update = useMutation({
    mutationFn: (priority: number) =>
      apiClient.put<Provider>(`/content/ui/config/providers/${provider.id}`, { priority }),
    onSuccess: () => {
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1600);
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
    },
    onError: () => setValue(String(provider.priority)),
  });

  return (
    <span className="inline-flex items-center gap-2 justify-end">
      <Input
        type="number"
        value={value}
        disabled={!provider.is_active || update.isPending}
        aria-label={`Prioridade de ${PROVIDER_LABEL[provider.provider]}`}
        title="Número menor é tentado primeiro entre provedores do mesmo tipo"
        className="w-20 text-right font-mono"
        onChange={(event) => setValue(event.target.value)}
        onBlur={() => {
          const next = Number(value);
          if (!Number.isNaN(next) && next !== provider.priority) update.mutate(next);
        }}
      />
      <span className="w-14 text-[11px] text-[var(--text)]">
        {update.isPending ? "salvando…" : saved ? "salvo" : update.isError ? "falhou" : ""}
      </span>
    </span>
  );
}

export function Providers() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [kind, setKind] = useState<Provider["kind"]>("image");
  const [providerName, setProviderName] = useState<Provider["provider"]>("falai");
  const [credentials, setCredentials] = useState("");
  const [priority, setPriority] = useState(0);

  const providers = useQuery({
    queryKey: ["config", "providers"],
    queryFn: () => apiClient.get<Provider[]>("/content/ui/config/providers"),
  });

  const create = useMutation({
    mutationFn: (payload: ProviderCreatePayload) =>
      apiClient.post<Provider>("/content/ui/config/providers", payload),
    onSuccess: () => {
      setCredentials("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Provider>(`/content/ui/config/providers/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "providers"] }),
  });

  const invalidCredentials = apiErrorStatus(create.error) === 422;

  const columns: Array<Column<Provider>> = [
    { key: "kind", header: "Tipo", width: "8rem", render: (row) => KIND_LABEL[row.kind] },
    {
      key: "provider",
      header: "Provedor",
      render: (row) => <span className="font-medium">{PROVIDER_LABEL[row.provider]}</span>,
    },
    {
      key: "priority",
      header: "Prioridade",
      align: "right",
      width: "13rem",
      render: (row) => <PriorityCell provider={row} />,
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (row) => <EntityChip state={row.is_active ? "active" : "inactive"} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (row) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={deactivate.isPending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !row.is_active,
                onConfirm: () => deactivate.mutate(row.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Provedores"
      description="Serviços de geração de imagem, vídeo e voz. Dentro de um mesmo tipo, o de menor prioridade é tentado primeiro."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button variant="primary" onClick={() => setDrawerOpen(true)}>
            <Plus size={15} />
            Adicionar provedor
          </Button>
        </RequireRole>
      }
    >
      <DataTable
        columns={columns}
        rows={providers.data}
        rowKey={(row) => row.id}
        isLoading={providers.isLoading}
        isError={providers.isError}
        emptyTitle="Nenhum provedor configurado"
        emptyHint="Sem provedor, a automação não consegue gerar conteúdo."
      />

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Adicionar provedor"
        description="A credencial é enviada ao servidor e não volta para esta tela."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({
              kind,
              provider: providerName,
              credentials,
              config: {},
              priority,
            });
          }}
        >
          <Field label="Tipo">
            <Select
              value={kind}
              onChange={(event) => setKind(event.target.value as Provider["kind"])}
            >
              <option value="image">Imagem</option>
              <option value="video">Vídeo</option>
              <option value="voice">Voz</option>
            </Select>
          </Field>
          <Field label="Provedor">
            <Select
              value={providerName}
              onChange={(event) => setProviderName(event.target.value as Provider["provider"])}
            >
              <option value="wavespeed">Wavespeed</option>
              <option value="falai">fal.ai</option>
              <option value="gemini">Gemini</option>
              <option value="elevenlabs">ElevenLabs</option>
            </Select>
          </Field>
          <Field
            label="Chave de API"
            error={invalidCredentials ? "Credencial inválida para este provedor." : null}
          >
            <Input
              type="password"
              value={credentials}
              onChange={(event) => setCredentials(event.target.value)}
              placeholder="Chave de API"
              required
            />
          </Field>
          <Field
            label="Prioridade"
            hint="Número menor é tentado primeiro entre provedores do mesmo tipo."
          >
            <Input
              type="number"
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || !credentials.trim()}
            >
              {create.isPending ? "Adicionando…" : "Adicionar"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Validar no navegador**

Em `/config/providers`: editar a prioridade e sair do campo mostra "salvando…" e depois "salvo"; a credencial nunca aparece na tabela; provedor inativo tem o campo de prioridade desabilitado.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/Providers.tsx
git commit -m "feat(webui): rebuild the providers screen, with visible save state on priority"
```

---

## Task 10: Contas sociais

**Files:**
- Modify: `webui/src/pages/config/SocialAccounts.tsx` (arquivo inteiro, 121 linhas hoje)

**Interfaces:**
- Consumes: primitivas das tasks 1-6, mais `PlatformIcon`/`PLATFORMS`/`PLATFORM_LABEL`/`Platform` de `components/ui/PlatformIcon`
- Produces: nada para tasks seguintes

- [ ] **Step 1: Reescrever `SocialAccounts.tsx`**

Duas correções além do visual:
1. Os três controles do formulário hoje não têm `<label>`, só `placeholder` — que some ao digitar. Todos ganham `Field`.
2. A lista de plataformas estava escrita à mão no `<select>`. Passa a vir de `PLATFORMS`, que já existe e é a lista das seis com adaptador no backend.

Esta é a primeira tela com escopo: usa `ScopeBar` e mostra um `EmptyState` quando nenhum cliente foi escolhido.

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Feedback";
import {
  PLATFORMS,
  PLATFORM_LABEL,
  PlatformIcon,
  type Platform,
} from "../../components/ui/PlatformIcon";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip, type EntityState } from "../../components/settings/EntityChip";
import type { Client, SocialAccount, SocialAccountCreatePayload } from "../../lib/types";

export function SocialAccounts() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [platform, setPlatform] = useState<Platform>("instagram");
  const [externalAccountId, setExternalAccountId] = useState("");
  const [credentials, setCredentials] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const accounts = useQuery({
    queryKey: ["config", "social-accounts", clientId],
    queryFn: () =>
      apiClient.get<SocialAccount[]>(`/content/ui/config/clients/${clientId}/social-accounts`),
    enabled: clientId !== null,
  });

  const create = useMutation({
    mutationFn: (payload: SocialAccountCreatePayload) =>
      apiClient.post<SocialAccount>("/content/ui/config/social-accounts", payload),
    onSuccess: () => {
      setExternalAccountId("");
      setCredentials("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<SocialAccount>(`/content/ui/config/social-accounts/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] }),
  });

  const columns: Array<Column<SocialAccount>> = [
    {
      key: "platform",
      header: "Plataforma",
      width: "12rem",
      render: (account) => (
        <span className="inline-flex items-center gap-2">
          <PlatformIcon platform={account.platform as Platform} size={14} />
          {PLATFORM_LABEL[account.platform as Platform] ?? account.platform}
        </span>
      ),
    },
    {
      key: "account",
      header: "Conta",
      render: (account) => (
        <span className="font-mono text-[12px]">{account.external_account_id}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (account) => <EntityChip state={account.status as EntityState} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (account) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={revoke.isPending}
            actions={[
              {
                label: "Revogar",
                danger: true,
                disabled: account.status !== "active",
                onConfirm: () => revoke.mutate(account.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Contas sociais"
      description="As contas onde as peças aprovadas são publicadas, por cliente."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={clientId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Conectar conta
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Cliente"
        placeholder="Selecione um cliente"
        options={clients.data?.map((client) => ({ id: client.id, label: client.name }))}
        value={clientId}
        onChange={setClientId}
        isLoading={clients.isLoading}
      />

      {clientId === null ? (
        <Card>
          <EmptyState
            title="Escolha um cliente"
            hint="As contas sociais são organizadas por cliente. Selecione um acima para ver as dele."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={accounts.data}
          rowKey={(account) => account.id}
          isLoading={accounts.isLoading}
          isError={accounts.isError}
          emptyTitle="Nenhuma conta conectada"
          emptyHint="Conecte uma conta para que este cliente possa publicar."
        />
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Conectar conta"
        description="A credencial é enviada ao servidor e não volta para esta tela."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId === null) return;
            create.mutate({
              client_id: clientId,
              platform,
              external_account_id: externalAccountId,
              credentials,
            });
          }}
        >
          <Field label="Plataforma">
            <Select
              value={platform}
              onChange={(event) => setPlatform(event.target.value as Platform)}
            >
              {PLATFORMS.map((option) => (
                <option key={option} value={option}>
                  {PLATFORM_LABEL[option]}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Identificador da conta"
            hint="O id que a plataforma usa para esta conta, não o @ de exibição."
          >
            <Input
              value={externalAccountId}
              onChange={(event) => setExternalAccountId(event.target.value)}
              placeholder="ID da conta na plataforma"
              required
            />
          </Field>
          <Field label="Credencial de acesso">
            <Input
              type="password"
              value={credentials}
              onChange={(event) => setCredentials(event.target.value)}
              placeholder="Token ou chave de acesso"
              required
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || !externalAccountId.trim() || !credentials.trim()}
            >
              {create.isPending ? "Conectando…" : "Conectar"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Validar no navegador**

Em `/config/social-accounts`: sem cliente escolhido, aparece "Escolha um cliente" e o botão de conectar fica desabilitado; escolhido um cliente, a tabela carrega com ícone de plataforma; os três campos do drawer têm label visível ao digitar.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/SocialAccounts.tsx
git commit -m "feat(webui): rebuild the social accounts screen with real field labels"
```

---

## Task 11: Templates de geração

**Files:**
- Modify: `webui/src/pages/config/GenerationTemplates.tsx` (arquivo inteiro, 208 linhas hoje)

**Interfaces:**
- Consumes: primitivas das tasks 1-6
- Produces: nada para tasks seguintes

- [ ] **Step 1: Reescrever `GenerationTemplates.tsx`**

É a maior das sete. Preservar tudo que já funciona: os presets de proporção com a opção "custom", a query de avatares dependente do cliente da campanha selecionada, e a separação entre `generation_prompt` e `narration_script` (que foi um fix deliberado, commit `b303adc`).

Escopo por campanha, via `ScopeBar`.

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Feedback";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select, Textarea } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Avatar, Campaign, GenerationTemplate } from "../../lib/types";

const ASPECT_RATIO_PRESETS = ["9:16", "16:9", "1:1", "4:5"];

const TYPE_LABEL: Record<GenerationTemplate["type"], string> = {
  image: "Imagem",
  video: "Vídeo",
  audio: "Áudio",
};

export function GenerationTemplates() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [type, setType] = useState<GenerationTemplate["type"]>("image");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [narrationScript, setNarrationScript] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [customAspectRatio, setCustomAspectRatio] = useState("");
  const [avatarId, setAvatarId] = useState<number | null>(null);
  const [voiceId, setVoiceId] = useState("");

  const effectiveAspectRatio = aspectRatio === "custom" ? customAspectRatio : aspectRatio;

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const selectedCampaign = campaigns.data?.find((campaign) => campaign.id === campaignId);

  const avatars = useQuery({
    queryKey: ["config", "avatars", selectedCampaign?.client_id],
    queryFn: () =>
      apiClient.get<Avatar[]>(`/content/ui/config/clients/${selectedCampaign?.client_id}/avatars`),
    enabled: selectedCampaign !== undefined,
  });

  const templates = useQuery({
    queryKey: ["config", "templates", campaignId],
    queryFn: () =>
      apiClient.get<GenerationTemplate[]>(`/content/ui/config/campaigns/${campaignId}/templates`),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<GenerationTemplate>(`/content/ui/config/campaigns/${campaignId}/templates`, {
        campaign_id: campaignId,
        type,
        generation_prompt: generationPrompt,
        narration_script: narrationScript || null,
        is_synthetic_media: false,
        aspect_ratio: effectiveAspectRatio,
        avatar_id: avatarId,
        voice_id: voiceId || null,
      }),
    onSuccess: () => {
      setGenerationPrompt("");
      setNarrationScript("");
      setAvatarId(null);
      setVoiceId("");
      setAspectRatio("9:16");
      setCustomAspectRatio("");
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<GenerationTemplate>(`/content/ui/config/templates/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] }),
  });

  const columns: Array<Column<GenerationTemplate>> = [
    { key: "type", header: "Tipo", width: "8rem", render: (row) => TYPE_LABEL[row.type] },
    {
      key: "prompt",
      header: "Prompt",
      render: (row) => (
        // Prompts run long; one line with an ellipsis keeps rows the same
        // height, and the full text is in the title attribute.
        <span className="block max-w-xl truncate" title={row.generation_prompt ?? undefined}>
          {row.generation_prompt ?? "(sem prompt)"}
        </span>
      ),
    },
    {
      key: "aspect",
      header: "Proporção",
      width: "8rem",
      render: (row) => <span className="font-mono text-[12px]">{row.aspect_ratio}</span>,
    },
    {
      key: "status",
      header: "Status",
      width: "8rem",
      render: (row) => <EntityChip state={row.is_active ? "active" : "inactive"} />,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (row) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={deactivate.isPending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !row.is_active,
                onConfirm: () => deactivate.mutate(row.id),
              },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Templates de geração"
      description="O molde de cada peça que a automação gera para uma campanha."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={campaignId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Novo template
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Campanha"
        placeholder="Selecione uma campanha"
        options={campaigns.data?.map((campaign) => ({ id: campaign.id, label: campaign.name }))}
        value={campaignId}
        onChange={setCampaignId}
        isLoading={campaigns.isLoading}
      />

      {campaignId === null ? (
        <Card>
          <EmptyState
            title="Escolha uma campanha"
            hint="Cada campanha tem seus próprios templates. Selecione uma acima para ver os dela."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={templates.data}
          rowKey={(row) => row.id}
          isLoading={templates.isLoading}
          isError={templates.isError}
          emptyTitle="Nenhum template nesta campanha"
          emptyHint="Sem template, a automação não sabe o que gerar."
        />
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Novo template"
        description="Define o que a automação gera para cada peça desta campanha."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId !== null && generationPrompt.trim() && effectiveAspectRatio.trim()) {
              create.mutate();
            }
          }}
        >
          <Field label="Tipo">
            <Select
              value={type}
              onChange={(event) =>
                setType(event.target.value as GenerationTemplate["type"])
              }
            >
              <option value="image">Imagem</option>
              <option value="video">Vídeo</option>
              <option value="audio">Áudio</option>
            </Select>
          </Field>
          <Field label="Prompt de geração" hint="O que o provedor deve criar.">
            <Textarea
              value={generationPrompt}
              onChange={(event) => setGenerationPrompt(event.target.value)}
              placeholder="Prompt de geração"
              required
            />
          </Field>
          <Field
            label="Roteiro de narração"
            hint="Opcional. Texto para a narração em áudio e vídeo — sem isso, o prompt de geração é usado."
          >
            <Textarea
              value={narrationScript}
              onChange={(event) => setNarrationScript(event.target.value)}
              placeholder="Roteiro de narração"
            />
          </Field>
          <Field label="Proporção">
            <Select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)}>
              {ASPECT_RATIO_PRESETS.map((preset) => (
                <option key={preset} value={preset}>
                  {preset}
                </option>
              ))}
              <option value="custom">Outra…</option>
            </Select>
          </Field>
          {aspectRatio === "custom" ? (
            <Field label="Proporção personalizada">
              <Input
                value={customAspectRatio}
                onChange={(event) => setCustomAspectRatio(event.target.value)}
                placeholder="ex: 21:9"
                required
              />
            </Field>
          ) : null}
          <Field label="Avatar">
            <Select
              value={avatarId ?? ""}
              onChange={(event) => setAvatarId(Number(event.target.value) || null)}
            >
              <option value="">Sem avatar</option>
              {avatars.data?.map((avatar) => (
                <option key={avatar.id} value={avatar.id}>
                  {avatar.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Voice ID"
            hint="Opcional. Identificador da voz no provedor — não há lista para escolher, é o código que o provedor fornece."
          >
            <Input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="ID da voz no provedor"
            />
          </Field>
          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={
                create.isPending ||
                campaignId === null ||
                !generationPrompt.trim() ||
                !effectiveAspectRatio.trim()
              }
            >
              {create.isPending ? "Criando…" : "Criar template"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Validar no navegador**

Em `/config/templates`: sem campanha, aparece o estado explicativo; escolhida uma campanha, a lista de avatares no drawer é a do cliente dessa campanha; escolher "Outra…" na proporção revela o campo livre; prompts longos não quebram a altura da linha.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/GenerationTemplates.tsx
git commit -m "feat(webui): rebuild the generation templates screen"
```

---

## Task 12: Avatares

**Files:**
- Modify: `webui/src/pages/config/Avatars.tsx` (arquivo inteiro, 132 linhas hoje)

**Interfaces:**
- Consumes: primitivas das tasks 1-6 (menos `DataTable` — esta tela é grade)
- Produces: nada para tasks seguintes

- [ ] **Step 1: Reescrever `Avatars.tsx`**

Única tela em grade: a imagem de referência é o dado principal, e uma miniatura de 24px numa célula esconderia justamente o que a pessoa foi ver.

Três correções além do visual:
1. `<input type="file">` cru vira área de seleção com prévia da imagem antes do envio.
2. `voice_provider` deixa de ser texto livre com dica "ex: elevenlabs" e vira `Select`.
3. Imagem que falha ao carregar mostra placeholder — o avatar continua identificável pelo nome.

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageOff, Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState, Skeleton } from "../../components/ui/Feedback";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import { EntityChip } from "../../components/settings/EntityChip";
import type { Avatar, Client } from "../../lib/types";

const VOICE_PROVIDERS = [
  { value: "elevenlabs", label: "ElevenLabs" },
  { value: "gemini", label: "Gemini" },
];

function AvatarCard({
  avatar,
  onDeactivate,
  pending,
}: {
  avatar: Avatar;
  onDeactivate: () => void;
  pending: boolean;
}) {
  const [broken, setBroken] = useState(false);

  return (
    <Card className="overflow-hidden flex flex-col">
      <div className="aspect-[4/5] bg-[var(--code-bg)] flex items-center justify-center">
        {broken || !avatar.reference_image_url ? (
          <ImageOff size={20} className="text-[var(--text)]" aria-hidden />
        ) : (
          <img
            src={avatar.reference_image_url}
            alt={`Imagem de referência de ${avatar.name}`}
            loading="lazy"
            onError={() => setBroken(true)}
            className="w-full h-full object-cover"
          />
        )}
      </div>
      <div className="flex items-start justify-between gap-2 px-3 py-2.5">
        <div className="min-w-0">
          <p className="m-0 truncate text-[13px] font-medium text-[var(--text-h)]">
            {avatar.name}
          </p>
          <EntityChip
            state={avatar.is_active ? "active" : "inactive"}
            className="mt-1.5"
          />
        </div>
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={pending}
            actions={[
              {
                label: "Desativar",
                danger: true,
                disabled: !avatar.is_active,
                onConfirm: onDeactivate,
              },
            ]}
          />
        </RequireRole>
      </div>
    </Card>
  );
}

export function Avatars() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [name, setName] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [voiceProvider, setVoiceProvider] = useState("");
  const [voiceId, setVoiceId] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const avatars = useQuery({
    queryKey: ["config", "avatars", clientId],
    queryFn: () => apiClient.get<Avatar[]>(`/content/ui/config/clients/${clientId}/avatars`),
    enabled: clientId !== null,
  });

  function resetForm() {
    setName("");
    setImageFile(null);
    // Object URLs are leaked memory until revoked, and the form can be filled
    // and cancelled repeatedly without ever submitting.
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setVoiceProvider("");
    setVoiceId("");
  }

  const create = useMutation({
    // uploadFile, not post: the avatar carries a file, and the client has a
    // separate method that sends FormData without forcing a JSON content type.
    mutationFn: (formData: FormData) =>
      apiClient.uploadFile<Avatar>("/content/ui/config/avatars", formData),
    onSuccess: () => {
      resetForm();
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Avatar>(`/content/ui/config/avatars/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] }),
  });

  return (
    <SettingsPage
      title="Avatares"
      description="As pessoas sintéticas que aparecem nas peças de vídeo, por cliente."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={clientId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Novo avatar
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Cliente"
        placeholder="Selecione um cliente"
        options={clients.data?.map((client) => ({ id: client.id, label: client.name }))}
        value={clientId}
        onChange={setClientId}
        isLoading={clients.isLoading}
      />

      {clientId === null ? (
        <Card>
          <EmptyState
            title="Escolha um cliente"
            hint="Os avatares são organizados por cliente. Selecione um acima para ver os dele."
          />
        </Card>
      ) : avatars.isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="aspect-[4/5] w-full" />
          ))}
        </div>
      ) : avatars.isError ? (
        <Card>
          <EmptyState
            title="Não foi possível carregar"
            hint="Verifique a conexão com o servidor e tente novamente."
          />
        </Card>
      ) : !avatars.data || avatars.data.length === 0 ? (
        <Card>
          <EmptyState
            title="Nenhum avatar cadastrado"
            hint="Crie um avatar para poder usá-lo nos templates de vídeo deste cliente."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {avatars.data.map((avatar) => (
            <AvatarCard
              key={avatar.id}
              avatar={avatar}
              pending={deactivate.isPending}
              onDeactivate={() => deactivate.mutate(avatar.id)}
            />
          ))}
        </div>
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Novo avatar"
        description="A imagem de referência define a aparência usada na geração."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId === null || !imageFile) return;
            const formData = new FormData();
            formData.append("client_id", String(clientId));
            formData.append("name", name);
            if (voiceProvider) formData.append("voice_provider", voiceProvider);
            if (voiceId) formData.append("voice_id", voiceId);
            formData.append("file", imageFile);
            create.mutate(formData);
          }}
        >
          <Field label="Nome">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Nome do avatar"
              required
            />
          </Field>

          {/* Spans rather than divs: this sits inside Field's <label>, which
              only accepts phrasing content. `flex` on a span behaves the same. */}
          <Field label="Imagem de referência" hint="JPG ou PNG. É a aparência que a geração vai reproduzir.">
            <span className="flex items-center gap-3">
              <span className="w-20 h-24 shrink-0 rounded-[4px] border border-[var(--border)] bg-[var(--code-bg)] flex items-center justify-center overflow-hidden">
                {previewUrl ? (
                  <img src={previewUrl} alt="Prévia" className="w-full h-full object-cover" />
                ) : (
                  <ImageOff size={18} className="text-[var(--text)]" aria-hidden />
                )}
              </span>
              <input
                type="file"
                accept="image/*"
                required
                onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  if (previewUrl) URL.revokeObjectURL(previewUrl);
                  setImageFile(file);
                  setPreviewUrl(file ? URL.createObjectURL(file) : null);
                }}
                className={
                  "flex-1 min-w-0 text-[12px] text-[var(--text)] " +
                  "file:mr-3 file:h-8 file:px-3 file:rounded-[4px] file:border file:border-[var(--border)] " +
                  "file:bg-[var(--card-bg)] file:text-[13px] file:font-medium file:text-[var(--text-h)] " +
                  "file:cursor-pointer"
                }
              />
            </span>
          </Field>

          <Field label="Provedor de voz" hint="Opcional. Necessário apenas para peças com narração.">
            <Select
              value={voiceProvider}
              onChange={(event) => setVoiceProvider(event.target.value)}
            >
              <option value="">Nenhum</option>
              {VOICE_PROVIDERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Voice ID" hint="Opcional. O código da voz no provedor escolhido.">
            <Input
              value={voiceId}
              onChange={(event) => setVoiceId(event.target.value)}
              placeholder="ID da voz no provedor"
            />
          </Field>

          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || clientId === null || !imageFile || !name.trim()}
            >
              {create.isPending ? "Criando…" : "Criar avatar"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 2: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 3: Validar no navegador**

Em `/config/avatars`: a grade responde ao tamanho da janela (2 colunas estreito, até 5 largo); escolher um arquivo mostra a prévia antes de enviar; uma URL de imagem quebrada mostra o ícone de placeholder e o nome continua legível; criar um avatar limpa o formulário.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/Avatars.tsx
git commit -m "feat(webui): rebuild the avatars screen as a thumbnail grid"
```

---

## Task 13: Regras de aprovação e o editor de condição

A tela mais complexa e a de maior ganho: hoje pede JSON digitado à mão, com erro de sintaxe só aparecendo depois de submeter.

**Files:**
- Create: `webui/src/lib/approvalCondition.ts`
- Modify: `webui/src/pages/config/ApprovalRules.tsx` (arquivo inteiro, 140 linhas hoje)

**Interfaces:**
- Consumes: primitivas das tasks 1-6
- Produces:
  - `CONTENT_CATEGORIES: ReadonlyArray<{ value: string; label: string }>`
  - `RISK_LEVELS: ReadonlyArray<{ value: string; label: string }>`
  - `readCondition(condition: Record<string, unknown>): { categories: string[]; risks: string[] } | null`
  - `buildCondition(categories: string[], risks: string[]): Record<string, string[]>`
  - `describeCondition(condition: Record<string, unknown>): string`

- [ ] **Step 1: Escrever `webui/src/lib/approvalCondition.ts`**

A semântica vem de `rule_matches` (`app/services/content/automation_scheduler.py:178-198`) e **precisa ser dita certo na tela**: E entre campos, ou dentro de um campo, condição vazia bate com tudo, chave desconhecida nunca bate.

```ts
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

const CATEGORY_LABEL = new Map(CONTENT_CATEGORIES.map((item) => [item.value, item.label]));
const RISK_LABEL = new Map(RISK_LEVELS.map((item) => [item.value, item.label]));

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
```

- [ ] **Step 2: Verificar a semântica das frases geradas**

Não há suíte para automatizar isso, então conferir à mão no console do navegador (ou com `node --experimental-strip-types`) que estas quatro entradas produzem estas quatro saídas:

```
{}                                              → "para qualquer peça"
{risk_level: ["high","medium"]}                 → "quando o risco for alto ou médio"
{risk_level: ["high"], content_category: ["medical","legal"]}
                                                → "quando o risco for alto e a categoria for médico ou jurídico"
{foo: ["bar"]}                                  → "condição não reconhecida — esta regra nunca bate"
```

O terceiro é o que importa mais: "e" entre os grupos, "ou" dentro de um. Invertido, a tela ensinaria o modelo errado.

- [ ] **Step 3: Reescrever `ApprovalRules.tsx`**

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Feedback";
import { cn } from "../../components/ui/cn";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { ScopeBar } from "../../components/settings/ScopeBar";
import { DataTable, type Column } from "../../components/settings/DataTable";
import { RowActions } from "../../components/settings/RowActions";
import { Drawer } from "../../components/settings/Drawer";
import { Field } from "../../components/settings/Field";
import { Input, Select } from "../../components/settings/Controls";
import {
  CONTENT_CATEGORIES,
  RISK_LEVELS,
  buildCondition,
  describeCondition,
} from "../../lib/approvalCondition";
import type { ApprovalRule, ApprovalRulePayload, Campaign } from "../../lib/types";

const ACTION_LABEL: Record<ApprovalRule["action"], string> = {
  auto_approve: "Aprovar sozinho",
  require_review: "Requer revisão",
};

function ChipGroup({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset className="m-0 p-0 border-0">
      <legend className="mb-1.5 p-0 text-[13px] font-medium text-[var(--text-h)]">
        {label}
      </legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(option.value)}
              className={cn(
                "h-7 px-3 rounded-full border text-[12px] font-medium cursor-pointer transition-colors",
                active
                  ? "bg-ink text-white border-transparent"
                  : "bg-[var(--card-bg)] text-[var(--text-h)] border-[var(--border)] hover:bg-[var(--code-bg)]",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function ApprovalRules() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [action, setAction] = useState<ApprovalRule["action"]>("require_review");
  const [priority, setPriority] = useState(10);
  const [categories, setCategories] = useState<string[]>([]);
  const [risks, setRisks] = useState<string[]>([]);

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const rules = useQuery({
    queryKey: ["config", "approval-rules", campaignId],
    queryFn: () =>
      apiClient.get<ApprovalRule[]>(
        `/content/ui/config/campaigns/${campaignId}/approval-rules`,
      ),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    // Reading is nested under the campaign, but creating is not: the POST goes
    // to the flat collection with campaign_id in the body. Do not "fix" this
    // into a nested path — that route does not exist on the backend.
    mutationFn: (payload: ApprovalRulePayload) =>
      apiClient.post<ApprovalRule>("/content/ui/config/approval-rules", payload),
    onSuccess: () => {
      setCategories([]);
      setRisks([]);
      setDrawerOpen(false);
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<ApprovalRule>(`/content/ui/config/approval-rules/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] }),
  });

  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  // Lowest priority first — the order the scheduler evaluates them in. The
  // backend does not promise an order, so the client establishes one.
  const sortedRules = rules.data
    ? [...rules.data].sort((a, b) => a.priority - b.priority)
    : undefined;

  const columns: Array<Column<ApprovalRule>> = [
    {
      key: "priority",
      header: "Prioridade",
      width: "8rem",
      render: (rule) => <span className="font-mono text-[12px]">{rule.priority}</span>,
    },
    {
      key: "action",
      header: "Ação",
      width: "12rem",
      render: (rule) => <span className="font-medium">{ACTION_LABEL[rule.action]}</span>,
    },
    {
      key: "condition",
      header: "Condição",
      render: (rule) => (
        <span className="text-[var(--text)]">{describeCondition(rule.condition)}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      width: "5rem",
      render: (rule) => (
        <RequireRole role="admin" fallback={null}>
          <RowActions
            pending={remove.isPending}
            actions={[
              { label: "Excluir", danger: true, onConfirm: () => remove.mutate(rule.id) },
            ]}
          />
        </RequireRole>
      ),
    },
  ];

  return (
    <SettingsPage
      title="Regras de aprovação"
      description="Cada peça gerada é checada contra estas regras, da menor prioridade para a maior. A primeira que bater decide se a peça é aprovada sozinha ou vai para revisão humana."
      action={
        <RequireRole role="admin" fallback={null}>
          <Button
            variant="primary"
            disabled={campaignId === null}
            onClick={() => setDrawerOpen(true)}
          >
            <Plus size={15} />
            Nova regra
          </Button>
        </RequireRole>
      }
    >
      <ScopeBar
        label="Campanha"
        placeholder="Selecione uma campanha"
        options={campaigns.data?.map((campaign) => ({ id: campaign.id, label: campaign.name }))}
        value={campaignId}
        onChange={setCampaignId}
        isLoading={campaigns.isLoading}
      />

      {campaignId === null ? (
        <Card>
          <EmptyState
            title="Escolha uma campanha"
            hint="Cada campanha tem suas próprias regras. Selecione uma acima para ver as dela."
          />
        </Card>
      ) : (
        <DataTable
          columns={columns}
          rows={sortedRules}
          rowKey={(rule) => rule.id}
          isLoading={rules.isLoading}
          isError={rules.isError}
          emptyTitle="Nenhuma regra nesta campanha"
          emptyHint="Sem regra que bata, a peça vai para revisão humana."
        />
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title="Nova regra"
        description="Sem nenhuma condição marcada, a regra vale para qualquer peça — útil como regra final, com a prioridade mais alta."
      >
        <form
          className="flex flex-col gap-4 items-stretch flex-nowrap m-0"
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId === null) return;
            create.mutate({
              campaign_id: campaignId,
              condition: buildCondition(categories, risks),
              action,
              priority,
            });
          }}
        >
          <Field label="Ação">
            <Select
              value={action}
              onChange={(event) =>
                setAction(event.target.value as ApprovalRule["action"])
              }
            >
              <option value="require_review">Requer revisão</option>
              <option value="auto_approve">Aprovar sozinho</option>
            </Select>
          </Field>

          <Field label="Prioridade" hint="Número menor é checado primeiro.">
            <Input
              type="number"
              value={priority}
              onChange={(event) => setPriority(Number(event.target.value))}
            />
          </Field>

          <ChipGroup
            label="Nível de risco"
            options={RISK_LEVELS}
            selected={risks}
            onToggle={(value) => setRisks((list) => toggle(list, value))}
          />

          <ChipGroup
            label="Categoria de conteúdo"
            options={CONTENT_CATEGORIES}
            selected={categories}
            onToggle={(value) => setCategories((list) => toggle(list, value))}
          />

          {/* The sentence updates as the chips change, so the operator reads
              the rule they are building instead of inferring it. */}
          <Card className="px-3 py-2.5">
            <p className="m-0 text-[12px] text-[var(--text)]">
              <span className="font-medium text-[var(--text-h)]">
                {ACTION_LABEL[action]}
              </span>{" "}
              {describeCondition(buildCondition(categories, risks))}
            </p>
          </Card>

          <div className="flex items-center gap-2 [&>button+button]:ml-0">
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending || campaignId === null}
            >
              {create.isPending ? "Criando…" : "Criar regra"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setDrawerOpen(false)}>
              Cancelar
            </Button>
          </div>
        </form>
      </Drawer>
    </SettingsPage>
  );
}
```

- [ ] **Step 4: Verificar build e lint**

```bash
cd webui && npm run build && npm run lint
```

- [ ] **Step 5: Validar no navegador**

Em `/config/approval-rules`, com uma campanha escolhida:

1. Criar regra sem marcar nada → a frase de prévia diz "para qualquer peça"; a linha criada mostra o mesmo.
2. Marcar risco Alto e Médio → "quando o risco for alto ou médio".
3. Marcar risco Alto **e** categoria Médico → "quando o risco for alto e a categoria for médico". Conferir que é "e" entre os dois e "ou" dentro de um.
4. As linhas aparecem ordenadas por prioridade crescente.
5. "Excluir" pede confirmação.

- [ ] **Step 6: Commit**

```bash
git add webui/src/lib/approvalCondition.ts webui/src/pages/config/ApprovalRules.tsx
git commit -m "feat(webui): replace the approval rule JSON textarea with a chip editor"
```

---

## Task 14: Passada final nas 7 telas

**Files:**
- Modify: qualquer uma das 7, conforme o que a revisão encontrar

- [ ] **Step 1: Percorrer as 7 telas no navegador, nos dois temas**

`/config/clients`, `/config/campaigns`, `/config/social-accounts`, `/config/avatars`, `/config/approval-rules`, `/config/templates`, `/config/providers`.

Conferir em cada uma: título em português, descrição presente, tabela ou grade alinhada, drawer abre e fecha, ação destrutiva confirma, estados de carregando/vazio/erro corretos.

- [ ] **Step 2: Medir o alinhamento, não olhar**

Em cada tela com tabela, no console:

```js
const rows = [...document.querySelectorAll('table tbody tr')];
const lefts = rows.map(r => r.querySelector('td').getBoundingClientRect().left);
console.log({ unique: [...new Set(lefts)] });
// Esperado: exatamente um valor — todas as primeiras células partem da mesma borda.
```

E que a página não role na horizontal:

```js
console.log(document.documentElement.scrollWidth <= window.innerWidth);
// Esperado: true, inclusive numa janela de 375px de largura.
```

- [ ] **Step 3: Conferir que nada fora de config regrediu**

`PieceQueue` (`/`), `PieceDetail`, `History` e `AuditLogList` continuam dependendo do bloco `@layer base` de `index.css`, que este plano não altera — só acrescenta regras da classe `.settings-drawer` ao fim do arquivo. Abrir `/` e `/history` e confirmar que estão como antes.

- [ ] **Step 4: Verificação final**

```bash
cd webui && npm run build && npm run lint
```

Esperado: build limpo; `oxlint` com exatamente os 3 warnings pré-existentes.

- [ ] **Step 5: Commit**

```bash
# Stage only the files this task actually changed — list them explicitly.
# `git add -A` here would sweep in unrelated work sitting in the tree.
git status --short webui/src
git add <os arquivos que a Task 14 alterou>
git commit -m "fix(webui): final pass over the standardised settings screens"
```

---

## Self-Review

**Cobertura da spec:**

| Requisito da spec | Task |
|---|---|
| `SettingsPage` | 6 |
| `ScopeBar` + estado vazio explicativo | 6, 10, 11, 12, 13 |
| `DataTable` com loading/vazio/erro | 3 |
| `RowActions` com confirmação inline | 4 |
| `Drawer` em `<dialog>` nativo + backdrop nos dois temas | 5 |
| `Field` + `Input`/`Select`/`Textarea` | 1 |
| `EntityChip` separado do `StatusChip` | 2 |
| 7 telas com título em português e tabela | 7-13 |
| Avatares em grade | 12 |
| Coluna Cliente em Campanhas | 8 |
| Editor de condição por chips | 13 |
| Frase legível da regra (E entre campos, ou dentro) | 13 |
| Condição não representável exibida, não reinterpretada | 13 (`readCondition` devolve `null`) |
| Ordenação por prioridade crescente | 13 |
| Labels reais em Contas sociais | 10 |
| Estado de salvo na prioridade de Provedores | 9 |
| Dropzone com prévia + select de provedor de voz em Avatares | 12 |
| Verificação medindo com `getBoundingClientRect` | 7, 14 |
| Não remover o CSS legado | Global Constraints, Task 14 Step 3 |

Sem lacunas.

**Corrigido durante a revisão** (o plano acima já está corrigido; registrado para que ninguém "restaure" o erro):

1. **`ApprovalRules` criava no endpoint errado.** O plano dizia `POST /content/ui/config/campaigns/{id}/approval-rules`, por simetria com a leitura. O real é `POST /content/ui/config/approval-rules` com `campaign_id` no corpo — a rota aninhada não existe.
2. **`Avatars` usava `apiClient.post`.** O real é `apiClient.uploadFile`, um método separado para `FormData`.
3. **`Field` mutava o DOM** por um `ref` callback com `querySelector` para amarrar `id` e `aria-describedby`. Trocado por `<label>` envolvente, que associa implicitamente — sem id para sincronizar e sem escrita fora do React.
4. **`Select` e o campo de imagem devolviam `<div>`** dentro do `<label>` do `Field`, o que é HTML inválido. Trocados por `<span>` com `block`/`flex`.

**Consistência de tipos:** `Column<T>` (Task 3) é usado como `Array<Column<X>>` nas tasks 7-13. `EntityState` (Task 2) é consumido em 7, 8, 9, 10, 11, 12. `RowAction` (Task 4) tem os mesmos campos em todas as chamadas. `ScopeOption` (Task 6) é montado por `.map()` nas tasks 10-13 com `{ id, label }`. `readCondition`/`buildCondition`/`describeCondition` (Task 13, Step 1) são chamados no Step 3 da mesma task, com as assinaturas declaradas.

**Ordem:** as tasks 1-6 são primitivas independentes entre si e podem ir em paralelo. A 7 é o piloto e precisa das seis. As 8-13 dependem das primitivas mas não umas das outras. A 14 fecha.
