"""Generate a valid RS256 session JWT for local manual testing of the content UI.

The real "parent app" (iframe host) does not exist yet, so this stands in for it.
Matches verify_user_session in app/controllers/content_auth.py: requires
tenant_id (int, must exist in content_tenants), user_id, role, exp.

Usage:
  python gerar_token.py --tenant-id 1 [--user-id local-admin] [--role admin] [--days 7]
"""
import argparse
import datetime
import os

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PRIVATE_KEY_PATH = "gerar_token_private.pem"
PUBLIC_KEY_PATH = "gerar_token_public.pem"


def load_or_create_keypair():
    if os.path.exists(PRIVATE_KEY_PATH) and os.path.exists(PUBLIC_KEY_PATH):
        with open(PRIVATE_KEY_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(PUBLIC_KEY_PATH, "rb") as f:
            public_pem = f.read()
        return private_key, public_pem

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with open(PRIVATE_KEY_PATH, "wb") as f:
        f.write(private_pem)
    with open(PUBLIC_KEY_PATH, "wb") as f:
        f.write(public_pem)
    return private_key, public_pem


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        type=int,
        required=True,
        help="ID real de um ContentTenant existente (veja GET /v1/content/tenants)",
    )
    parser.add_argument("--user-id", default="local-admin")
    parser.add_argument("--role", choices=["admin", "member"], default="admin")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    private_key, public_pem = load_or_create_keypair()

    payload = {
        "tenant_id": args.tenant_id,
        "user_id": args.user_id,
        "role": args.role,
        "name": args.user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=args.days),
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")

    print("=" * 70)
    print("1) Configure a public key no processo do backend (uma vez por sessão do servidor):")
    print(f'   export CONTENT_UI_JWT_PUBLIC_KEY="$(cat {PUBLIC_KEY_PATH})"')
    print()
    print("2) Token gerado:")
    print(token)
    print()
    print("3) Suba o backend (python main.py) e abra http://localhost:8080/login.html —")
    print("   página local que substitui o app mãe (ainda não existe). Cole o token e")
    print("   clique em Entrar; ela embeda a SPA num iframe e faz o postMessage sozinha.")
    print()
    print("   Rodando via `npm run dev` (Vite em :5173) em vez do build servido pelo")
    print("   backend? Cole isso no console do browser com http://localhost:5173 aberto:")
    print(f'   window.postMessage({{type: "session", token: "{token}"}}, "http://localhost:5173")')
    print("=" * 70)


if __name__ == "__main__":
    main()
