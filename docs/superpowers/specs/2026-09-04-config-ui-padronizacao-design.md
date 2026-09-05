# Design — Padronização das telas de configuração

> **Status:** Final / Aprovado para Implementação
> **Data:** 2026-09-04
> **Escopo:** `webui/` do `projeto-mosaic-automacao` — as 7 telas em `src/pages/config/`

## Contexto

O commit `d72c113` retematizou o webui para a linguagem visual do everyfeed.ai e trouxe
telas novas (calendário, agente, analytics, composer). As 7 telas de configuração ficaram
de fora: continuam sendo HTML sem classe nenhuma, apoiadas no bloco de seletores de tag
crua que vive em `index.css:147` (`@layer base`).

O resultado é uma descontinuidade visível: quem navega de `/analytics` para
`/config/providers` sai de uma tela com cards, chips e skeletons e cai numa `<ul>` com
texto concatenado por travessão.

As 7 telas repetem a mesma anatomia, sete vezes, sem nada compartilhado:

1. `<h1>` com o nome **em inglês** ("Clients", "Approval Rules") — enquanto o menu lateral
   já mostra "Clientes", "Regras de aprovação" (`AppShell.tsx:8-16`)
2. às vezes um `<select>` de escopo solto no topo (cliente ou campanha)
3. `{q.isLoading && <p>Carregando...</p>}` e `{q.isError && <p>Erro ao carregar.</p>}`
4. uma `<ul>` de itens em texto corrido, com botão de ação destrutiva inline
5. um `<form>` de criação empilhado embaixo, sempre aberto

### O que já existe e deve ser reusado

`components/ui/` tem `Card`, `MicroLabel`, `Button` (4 variantes, 2 tamanhos),
`StatusChip`, `Pill`, `PlatformIcon`, `Skeleton`, `SkeletonRows` e `EmptyState`. Nenhuma
das 7 telas importa qualquer um deles. O trabalho é em boa parte adoção do que já está
escrito, não invenção.

### O CSS legado não morre nesta rodada

`PieceQueue`, `PieceDetail`, `History` e `AuditLogList` também não foram migrados (0 e 2
ocorrências de `className`). O bloco `@layer base` de `index.css` continua sendo o que os
mantém legíveis, e sai do escopo desta spec. Preflight do Tailwind segue desligado pelo
mesmo motivo já documentado no topo do arquivo.

## Decisões de brainstorming

- **Anatomia: lista + painel lateral.** A tela é a lista. A criação sai do fluxo vertical
  e vai para um painel que abre sob demanda. Descartadas: duas colunas fixas (rouba metade
  da largura de tabelas que já têm 4-5 colunas) e tudo empilhado em cards (mantém o
  formulário ocupando espaço mesmo sem uso, que é a queixa original).
- **Lista: tabela em 6 telas, grade em Avatares.** Colunas nomeadas tornam os valores
  comparáveis entre linhas — necessário para prioridade de provedores e de regras.
  Avatares é a exceção porque a imagem de referência é o dado principal ali, e uma
  miniatura de 24px numa célula esconderia justamente o que a pessoa foi ver.
- **Escopo por tela, não global.** Um seletor global de cliente no cabeçalho seria mais
  coerente como produto, mas alcança calendário, fila e analytics — outro trabalho, com
  outro risco. Fica registrado como possível evolução, não como parte desta spec.
- **Sem dependência nova.** O painel lateral usa `<dialog>` nativo. O projeto não tem
  Radix nem headless UI, e um drawer não justifica introduzir um.
- **Escopo inclui os campos crus.** Não é só pintar: onde o formulário hoje exige que a
  pessoa saiba a forma interna do dado (o JSON das regras, o nome do provider de voz
  digitado à mão), o controle é substituído.

## Primitivas — `components/settings/`

Diretório novo, irmão de `components/ui/`. A divisão: `ui/` são peças de vocabulário
geral, já usadas fora de config; `settings/` são as peças da anatomia de uma tela de
configuração, e não têm consumidor fora dela.

| Componente | Responsabilidade | Depende de |
|---|---|---|
| `SettingsPage` | Título, linha de descrição, slot da ação primária | — |
| `ScopeBar` | Seleção de cliente/campanha + estado "nada escolhido" | `Select` |
| `DataTable` | Colunas nomeadas, cabeçalho `MicroLabel`, loading/vazio/erro | `Skeleton`, `EmptyState` |
| `RowActions` | Menu `⋯` no fim da linha, com confirmação inline | `Button` |
| `Drawer` | Painel lateral de criação | — |
| `Field` | Label + controle + hint + mensagem de erro | — |
| `Input` / `Select` / `Textarea` | Controles de formulário com Tailwind | — |
| `EntityChip` | ativo / inativo / arquivado / revogado | — |

### `DataTable`

Genérico sobre a linha, com colunas declaradas:

```ts
interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right";
  render: (row: T) => ReactNode;
}
```

Os três estados ficam dentro do componente, não repetidos em cada tela: `isLoading` →
`SkeletonRows`; `isError` → `EmptyState` com o texto de erro; lista vazia → `EmptyState`
com a mensagem que a tela passar. Hoje cada tela reimplementa isso em `<p>`.

### `Drawer`

`<dialog>` nativo com `showModal()`. A escolha entrega de graça o que uma div com backdrop
exigiria escrever: prender o foco dentro do painel, fechar no `Esc`, inertizar o fundo, e
devolver o foco ao botão que abriu. A entrada lateral é uma transição CSS sobre
`translateX`, respeitando `prefers-reduced-motion`.

Fecha em: `Esc`, clique no backdrop, botão cancelar, e sucesso da mutation. **Não** fecha
enquanto a mutation está em voo, nem quando ela falha — o erro aparece dentro do painel,
com o que foi digitado preservado.

### `EntityChip`

Vocabulário separado do `StatusChip`. O que existe hoje é o ciclo de vida de uma peça
(rascunho, gerando, publicada); config fala de outra coisa (ativo, inativo, arquivado,
revogado). São enums que mudam por razões diferentes, e juntá-los num componente só
acoplaria duas evoluções independentes. A aparência é a mesma — chip de 20px, cor por
significado — porque o usuário não deve perceber a distinção.

### `RowActions`

Ações destrutivas hoje disparam no primeiro clique: "Desativar" desativa, sem pergunta. O
padrão passa a ser confirmação **inline**, na própria linha — a célula de ação vira
"Confirmar? / Cancelar". Um modal seria interrupção grande demais para uma ação
reversível (todas são desativação lógica, não `DELETE`).

Exceção: `ApprovalRules` usa `DELETE` de verdade (`remove.mutate`). Mesma confirmação
inline, com o verbo dizendo a diferença ("Excluir" em vez de "Desativar").

## As 7 telas

Comum a todas: título traduzido, uma linha de descrição do que a tela controla, `DataTable`
no lugar da `<ul>`, criação no `Drawer`, `RequireRole role="admin"` preservado exatamente
onde já está (esta spec não mexe em permissão).

| Tela | Título | Colunas |
|---|---|---|
| `Clients` | Clientes | Nome · Status · ⋯ |
| `Campaigns` | Campanhas | Nome · Cliente · Horizonte · Status · ⋯ |
| `SocialAccounts` | Contas sociais | Plataforma · Conta · Status · ⋯ |
| `Avatars` | Avatares | *(grade, não tabela)* |
| `ApprovalRules` | Regras de aprovação | Prioridade · Ação · Condição · ⋯ |
| `GenerationTemplates` | Templates de geração | Tipo · Prompt · Proporção · Status · ⋯ |
| `Providers` | Provedores | Tipo · Provedor · Prioridade · Status · ⋯ |

`Campaigns` ganha a coluna "Cliente", que hoje não existe na lista — a tela mostra
campanhas de todos os clientes misturadas, sem dizer de quem é cada uma.

### Escopo (4 telas)

`Avatars` e `SocialAccounts` escopam por cliente; `GenerationTemplates` e `ApprovalRules`,
por campanha. Sem seleção, a tela hoje fica em branco. Passa a mostrar um `EmptyState`
explicando o que falta ("Escolha uma campanha para ver as regras de aprovação"), e a ação
primária fica desabilitada — não faz sentido criar uma regra sem campanha.

A seleção **não** persiste entre visitas. Guardar em `localStorage` traria a pergunta de
o que fazer quando o item guardado foi desativado desde então, e não há evidência de que
o incômodo justifique isso.

### Avatares — grade

Cards de miniatura com `reference_image_url`, nome, `EntityChip` e `RowActions`. Grade
responsiva (2 colunas no celular, até 5 no desktop). A imagem usa `object-cover` com
proporção fixa, `loading="lazy"`, e um placeholder neutro quando a URL falha — um avatar
sem prévia ainda precisa ser identificável pelo nome.

No formulário, o `<input type="file">` cru vira área de soltar arquivo com prévia da
imagem escolhida antes do envio, e `voice_provider` deixa de ser texto livre com dica
"ex: elevenlabs" e vira `Select`.

## Regras de aprovação — o editor de condição

É o pior caso das 7 telas e o de maior ganho. Hoje a condição é um `<textarea>` onde a
pessoa digita JSON, e um erro de sintaxe só aparece depois de submeter.

Os dois campos suportados são enums fechados no backend (`app/models/content.py:38-54`):

- `content_category` — 9 valores (medical, pharmaceutical, financial, insurance, legal,
  alcohol, gambling, political, regulated_product)
- `risk_level` — 4 valores (none, low, medium, high)

O `<textarea>` é substituído por dois grupos de chips de múltipla escolha, um por campo.

### Semântica, que a UI precisa dizer certo

`rule_matches` (`automation_scheduler.py:178-198`) define:

- **entre campos: E** — toda chave presente na condição precisa bater
- **dentro de um campo: ou** — o valor da peça precisa estar na lista
- **condição vazia: bate com tudo** — a regra curinga
- **chave desconhecida: nunca bate** — um typo cai para revisão humana, não passa batido

Nenhum chip marcado num campo significa que a chave **não entra** na condição — não que
ela case com lista vazia (que nunca bateria). Nenhum chip em nenhum dos dois campos
produz `{}`, a regra curinga.

A regra ganha uma frase gerada a partir da condição, mostrada tanto na tabela quanto no
formulário enquanto se edita:

```
Requer revisão   ·   quando o risco for alto ou médio
Requer revisão   ·   quando o risco for alto e a categoria for médico ou jurídico
Auto-aprovar     ·   para qualquer peça
```

### Condições que os chips não sabem representar

`ApprovalRule.condition` é `Record<string, unknown>`, e o banco pode ter regras com uma
chave fora das duas suportadas, ou com um valor que não é lista. Essas regras existem e o
scheduler as trata (nunca batem). A UI **não** pode reinterpretá-las nem apagá-las ao
salvar.

Tratamento: uma condição não representável é exibida na tabela como o JSON original em
`font-mono`, com um aviso de que essa regra nunca bate em peça nenhuma — o que é a
verdade, e é informação útil. O editor de chips não abre para ela. Como o CRUD atual só
tem criar e excluir (não há edição de regra), a única consequência prática é a
apresentação, mas a decisão fica registrada para quando a edição existir.

## Os outros campos crus

**Contas sociais** — os três controles do formulário não têm `<label>`, só `placeholder`,
que desaparece ao digitar; quem volta ao formulário meio preenchido não sabe mais o que é
cada campo. Ganham `Field` com label de verdade. `platform` vira `Select` com o
`PlatformIcon` que já existe, e a coluna da tabela mostra o mesmo ícone.

**Provedores** — a prioridade editável direto na célula é boa e fica, mas hoje dispara no
`onBlur` sem qualquer retorno visual: não dá para saber se salvou. Passa a mostrar estado
de salvando e de salvo, e a reverter para o valor anterior se a mutation falhar.

**Templates de geração** — o preset de proporção já existe e fica. `voice_id` continua
texto livre (é um identificador opaco do provider, não há lista para oferecer), mas ganha
hint dizendo isso.

## Testes

O `webui` não tem suíte de testes — não há `vitest` nem script `test` no `package.json`, e
nenhuma tela tem teste. Esta spec não introduz uma, o que seria uma decisão de projeto
maior que o trabalho em si.

A verificação é manual, via Playwright, contra o app rodando:

- cada uma das 7 telas: carrega, lista, cria pelo drawer, e a ação destrutiva pede
  confirmação
- estado sem escopo escolhido nas 4 telas que escopam
- estados de loading, vazio e erro do `DataTable`
- `Drawer`: `Esc` fecha, foco fica preso dentro, foco volta ao botão que abriu
- tema claro e escuro

**Alinhamento é verificado medindo**, com `getBoundingClientRect` via Playwright, não por
inspeção de screenshot — a diferença já custou uma rodada de retrabalho neste projeto.

## Não-objetivos

- **Migrar `PieceQueue`, `PieceDetail`, `History` e `AuditLogList`.** Também estão sem
  migrar, e também merecem — mas são outra área, com outro fluxo. Depois desta rodada, o
  bloco `@layer base` de `index.css` existirá apenas para elas, o que torna o escopo do
  próximo passo fácil de enxergar.
- **Remover o CSS legado de tags cruas.** Consequência do item acima.
- **Seletor global de cliente.** Registrado como evolução possível; alcança telas fora de
  config.
- **Edição de itens existentes.** O CRUD atual é criar e desativar/excluir. Adicionar
  edição é feature, não padronização.
- **Introduzir suíte de testes de frontend.** Decisão de projeto, fora desta spec.
- **Mexer no menu lateral.** Pedido explicitamente pelo autor: o problema é o conteúdo das
  telas, não a navegação.
- **Mexer em permissões.** `RequireRole` fica exatamente onde está.

## Riscos e pontos de atenção

- **Preflight desligado.** Utilitários do Tailwind já vencem o bloco `base` pela ordem de
  camadas declarada em `index.css:6`, mas cada propriedade que a regra de tag crua define
  precisa ser reafirmada na versão nova — o comentário em `Button.tsx:15-18` documenta
  exatamente essa armadilha, encontrada uma vez. Vale para `input`, `select`, `textarea` e
  `table` do mesmo jeito que valeu para `button`.
- **`<dialog>` e o tema.** O pseudo-elemento `::backdrop` não herda variáveis CSS do
  documento em todos os motores; a cor do backdrop precisa ser declarada nele
  explicitamente, nos dois temas.
- **Ordem de prioridade das regras.** A tabela ordena por `priority` crescente, que é a
  ordem em que o scheduler avalia (menor primeiro). A lista atual não ordena — vem na
  ordem do backend. Se a API não garantir ordenação, quem ordena é o cliente.
- **`Campaigns` precisa dos clientes para a coluna nova.** A tela já busca
  `config/clients` para o formulário, então é reuso de query, não requisição a mais.
