# Servidor Xtream das listas

Transforma as listas `.m3u8` deste repositorio num servidor **Xtream Codes** (usuario + senha), no mesmo
formato dos servicos de IPTV. O app baixa so a categoria que voce abre, em vez de carregar um arquivo de
300 MB. Filmes, series (episodios agrupados por serie/temporada) e canais ao vivo ficam separados.

> Para uma sessão do Claude executar tudo no PC, comece por `INSTRUCOES-CLAUDE.md`.

## Rodar (no PC)

Precisa de Docker (Docker Desktop no Windows/Mac).

```bash
git clone https://github.com/peresgabriel1207-byte/Iptv.git
cd Iptv
git checkout xtream-server        # ou master, depois de fazer o merge
cp .env.example .env              # edite XTREAM_USER e XTREAM_PASS
docker compose up -d --build
docker compose logs -f            # espera "indice pronto" (~15 s)
```

No app de IPTV (HM IPTV, Smarters, GSE...) escolha **Xtream Codes / Xtream API**:

| Campo | Valor |
|---|---|
| Servidor / URL | `http://IP_DO_PC:8080` |
| Usuario / Senha | os do `.env` |

- No celular na mesma rede Wi-Fi, use o IP local do PC (ex.: `http://192.168.0.10:8080`).
- Fora de casa: use uma VPN (ex.: Tailscale) em vez de abrir a porta na internet.
- Tambem funciona como M3U: `http://IP:8080/get.php?username=U&password=P&type_filter=live`
  (`type_filter`: `live`, `movie` ou `episode`; `&category=Nome` filtra por categoria).

## Como classifica

| Na lista | Vira |
|---|---|
| URL com `/movie/` | Filmes |
| URL com `/series/` e nome `Titulo S01E02` | Series -> temporadas -> episodios |
| o resto | Canais ao vivo |

`group-title` vira a categoria. Entradas com a mesma URL sao unificadas. O video **nao passa pelo seu
servidor**: ele redireciona o app para a URL original de cada item (baixo uso de banda e CPU).

## Manter igual ao repositorio original

Dois niveis, ambos automaticos:

1. **GitHub -> este repositorio** (`.github/workflows/sync-upstream.yml`, a cada 6 h).
   O original ja vem configurado: `Ramys/Iptv-Brasil-2026` (branch `master`). Nao precisa criar nada;
   so fazer o merge desta branch na `master`. Para trocar de original, crie as variaveis
   `UPSTREAM_REPO` / `UPSTREAM_BRANCH` em *Settings -> Secrets and variables -> Actions -> Variables*.
   Rode manualmente em *Actions -> Sincronizar com o repositorio original -> Run workflow*.
   Para sincronizar no seu PC: `scripts/sync-upstream.sh Ramys/Iptv-Brasil-2026 master`.
2. **Repositorio -> servidor**: o container faz `git pull` a cada `GIT_PULL_INTERVAL_MIN` minutos
   e reindexa sozinho quando as listas mudam.

O sync nunca mexe em `server/`, `scripts/`, `docker-compose.yml`, `.env.example` e
`.github/workflows/`, `LEIAME-SERVIDOR.md` e `INSTRUCOES-CLAUDE.md`; o resto e copiado do original (arquivos apagados la sao apagados aqui).

## Limites

- Os links dentro das listas sao de terceiros: o servidor so organiza, nao garante que o stream esteja no ar.
- Sem HTTPS nem protecao contra tentativas de senha: use senha forte e mantenha em rede local/VPN.
- Em `get_vod_streams` (127 mil filmes) o app pode pedir tudo de uma vez (~45 MB, ~5x menos com gzip).
