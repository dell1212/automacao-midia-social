import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { BarChart3, Bot, CalendarDays, ChevronDown, History, Layers, Settings } from "lucide-react";
import { useSession } from "../context/SessionProvider";
import { MicroLabel } from "./ui/Card";
import { cn } from "./ui/cn";

const CONFIG_LINKS = [
  { to: "/config/clients", label: "Clientes" },
  { to: "/config/campaigns", label: "Campanhas" },
  { to: "/config/social-accounts", label: "Contas sociais" },
  { to: "/config/avatars", label: "Avatares" },
  { to: "/config/approval-rules", label: "Regras de aprovação" },
  { to: "/config/templates", label: "Templates" },
  { to: "/config/providers", label: "Provedores" },
];

const ITEM =
  "flex items-center gap-2 h-8 px-2.5 rounded-[4px] text-[13px] font-medium no-underline " +
  "text-[var(--text)] hover:bg-[var(--code-bg)] hover:text-[var(--text-h)] transition-colors";
const ITEM_ACTIVE = "bg-ink text-white hover:bg-ink hover:text-white";

function Item({
  to,
  label,
  icon,
  end,
}: {
  to: string;
  label: string;
  icon?: React.ReactNode;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => cn(ITEM, isActive && ITEM_ACTIVE)}
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function AppShell() {
  const { session } = useSession();
  const { pathname } = useLocation();
  // Config is a group of seven screens; keeping it collapsed by default stops
  // the sidebar from being mostly settings, but it has to start open when the
  // current route is already inside it.
  const [configOpen, setConfigOpen] = useState(pathname.startsWith("/config"));

  return (
    <div className="flex flex-col md:flex-row min-h-svh w-full bg-[var(--bg)]">
      <aside
        className={
          "flex md:flex-col md:w-56 md:shrink-0 gap-1 p-3 " +
          "border-b md:border-b-0 md:border-r border-[var(--border)] bg-[var(--card-bg)] " +
          "overflow-x-auto md:overflow-x-visible"
        }
      >
        <div className="hidden md:flex items-center gap-2 px-2.5 pb-3">
          <span className="inline-block w-3 h-3 rounded-[2px] bg-lime" />
          <span className="text-[13px] font-semibold tracking-tight text-[var(--text-h)]">
            Automação
          </span>
        </div>

        <Item to="/calendar" label="Calendário" icon={<CalendarDays size={15} />} />
        <Item to="/" label="Fila de peças" icon={<Layers size={15} />} end />
        <Item to="/agent" label="Agente" icon={<Bot size={15} />} />
        <Item to="/analytics" label="Analytics" icon={<BarChart3 size={15} />} />
        <Item to="/history" label="Histórico" icon={<History size={15} />} />

        <div className="hidden md:block pt-3">
          <button
            type="button"
            onClick={() => setConfigOpen((open) => !open)}
            aria-expanded={configOpen}
            className={cn(ITEM, "w-full bg-transparent border-0 justify-between px-2.5")}
          >
            <span className="flex items-center gap-2">
              <Settings size={15} />
              Configurações
            </span>
            <ChevronDown
              size={14}
              className={cn("transition-transform", configOpen && "rotate-180")}
            />
          </button>
          {configOpen ? (
            <div className="flex flex-col gap-0.5 pl-4 pt-0.5">
              {CONFIG_LINKS.map((link) => (
                <Item key={link.to} to={link.to} label={link.label} />
              ))}
            </div>
          ) : null}
        </div>

        {/* Narrow viewports get the config screens inline instead of the
            collapsible group, so the whole nav stays one scrollable row. */}
        <div className="flex md:hidden gap-1">
          {CONFIG_LINKS.map((link) => (
            <Item key={link.to} to={link.to} label={link.label} />
          ))}
        </div>

        {session ? (
          <div className="hidden md:block mt-auto px-2.5 pt-3 border-t border-[var(--border)]">
            <MicroLabel>{session.tenant_name}</MicroLabel>
            <p className="m-0 mt-1 text-[12px] text-[var(--text)]">
              {session.name ?? session.user_id} · {session.role}
            </p>
          </div>
        ) : null}
      </aside>

      {/* Owns the page padding that `#root > div` used to provide before the
          layout route existed. */}
      <main className="flex-1 min-w-0 px-6 py-5 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
