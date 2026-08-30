import type { ReactNode } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SessionProvider, useSession } from "./context/SessionProvider";
import { ConfigNav } from "./components/ConfigNav";
import { PieceQueue } from "./pages/PieceQueue";
import { PieceDetail } from "./pages/PieceDetail";
import { Clients } from "./pages/config/Clients";

function Gate({ children }: { children: ReactNode }) {
  const { status } = useSession();

  if (status === "waiting") return <p>Aguardando sessão do app mãe...</p>;
  if (status === "loading") return <p>Validando sessão...</p>;
  if (status === "error") return <p>Sessão expirada ou inválida. Feche e reabra este painel.</p>;

  return <>{children}</>;
}

export function App() {
  return (
    <SessionProvider>
      <Gate>
        <BrowserRouter>
          <ConfigNav />
          <Routes>
            <Route path="/" element={<PieceQueue />} />
            <Route path="/pieces/:id" element={<PieceDetail />} />
            <Route path="/config/clients" element={<Clients />} />
          </Routes>
        </BrowserRouter>
      </Gate>
    </SessionProvider>
  );
}
