# Projeto Mosaic — Automação de Conteúdo

Módulo headless de automação de conteúdo (ideia → vídeo/imagem/áudio → postagem), pensado para
plugar em um app de assinatura vendido a agências e empresas. Produto irmão do `projeto-mosaic-agenda`
(agendamento/controle de cliente), contratável separadamente.

## Origem

Este projeto parte do pipeline de geração de vídeo do
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (MIT License, ver `LICENSE`),
mantendo `app/` (backend FastAPI: roteiro → material → legenda → trilha) como base e removendo a
WebUI Streamlit original — este projeto é API-only.

## Roadmap

Ver `docs/superpowers/specs/` para as specs de design de cada sub-projeto:

1. Fundação (dados, persistência, autenticação, esqueleto de API) — em design
2. Motor de geração estendido (+ imagens)
3. Motor de publicação (redes sociais)
4. Automação e aprovação
5. UI do módulo

## Rodando localmente

```bash
cp config.example.toml config.toml
pip install -r requirements.txt
python main.py
```
