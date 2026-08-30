import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/config/clients", label: "Clients" },
  { to: "/config/campaigns", label: "Campaigns" },
  { to: "/config/social-accounts", label: "Social Accounts" },
  { to: "/config/avatars", label: "Avatars" },
  { to: "/config/approval-rules", label: "Approval Rules" },
  { to: "/config/templates", label: "Templates" },
  { to: "/config/providers", label: "Providers" },
];

export function ConfigNav() {
  return (
    <nav>
      <NavLink to="/" end>
        Fila de peças
      </NavLink>
      {LINKS.map((link) => (
        <NavLink key={link.to} to={link.to}>
          {link.label}
        </NavLink>
      ))}
    </nav>
  );
}
