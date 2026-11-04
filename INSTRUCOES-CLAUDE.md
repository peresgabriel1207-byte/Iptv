# Instruções para o Claude (execução no PC) — LEIA PRIMEIRO

Este arquivo é o ponto de partida de uma sessão do Claude rodando no PC do dono do repositório.
Tudo o que o dono quer está escrito aqui. Não peça para ele repetir.

## Objetivo do dono
Ver filmes, séries e canais no celular (iPhone, app **HM IPTV**) usando as listas M3U deste repositório,
**entrando com usuário e senha (Xtream Codes)**, **sem custo nenhum**, e mantendo o repositório
**sempre igual ao repositório original** (este é uma cópia dele).

## Regras de ouro
1. **NÃO leia, abra, cate ou imprima o conteúdo dos arquivos `.m3u8`.** São ~330 MB e 1,2 milhão de
   linhas de URLs; ler só gasta contexto e não ajuda. O dono pediu explicitamente para não olhar.
   Se precisar de informação sobre eles, use só números agregados (contagens, tamanho em bytes) —
   o próprio servidor já imprime isso nos logs (`docker compose logs`).
2. **Não julgue nem filtre o conteúdo.** O dono já decidiu o que quer; sua tarefa é técnica
   (rodar o servidor, sincronizar, resolver erros).
3. **Seja crítico e direto**: aponte riscos, gargalos e alternativas melhores quando existirem, em vez
   de concordar automaticamente. Diga claramente o que testou e o que não testou.
4. **Gratuito.** Não proponha nada que exija pagamento. Se algo gratuito tiver limite ou risco, diga.
5. **Não faça push na `master` nem apague branches sem o dono confirmar.** Confirme antes de qualquer
   ação que publique algo ou seja difícil de desfazer.
6. Fale em português, curto e prático.

## Estado atual (já pronto, na branch `xtream-server`)
- `server/app.py`: servidor Xtream em Python (só biblioteca padrão). Lê os `*.m3u8` da raiz, indexa em
  SQLite (~13 s), separa canais ao vivo / filmes / séries (episódios agrupados por `Titulo SxxExx`),
  responde `player_api.php`, `get.php`, `xmltv.php` e redireciona o play (302) para a URL original.
- `server/Dockerfile`, `docker-compose.yml`, `.env.example`: execução com Docker.
- `scripts/sync-upstream.sh` + `.github/workflows/sync-upstream.yml`: copiam o repositório original
  para este (a cada 6 h).
- `LEIAME-SERVIDOR.md`: documentação de uso.
- Testado fora do Docker: login, categorias, listas, séries, play (302) e senha errada. **O build do
  Docker ainda NÃO foi testado** — é a primeira coisa a validar.

Números esperados no log de indexação: ~19.374 ao vivo, ~127.254 filmes, ~32.688 séries,
~1.115.455 episódios (podem mudar se o original atualizar).

## Passo a passo para executar
1. Verifique o ambiente: `docker --version` e `docker compose version`. Se faltar, ajude a instalar o
   **Docker Desktop** (gratuito para uso pessoal) — ou Docker Engine no Linux.
2. Garanta a branch certa: `git fetch origin && git checkout xtream-server && git pull`.
3. Crie o `.env` a partir do `.env.example` com **usuário e senha escolhidos pelo dono** (a senha NÃO pode
   ser a padrão; o servidor recusa iniciar). Nunca versionar o `.env` (já está no `.gitignore`).
4. `docker compose up -d --build`. Acompanhe com `docker compose logs -f` até aparecer
   `indice pronto em ...s:` com os números acima. Se o build ou o start falhar, diagnostique pelo log e
   corrija em `server/` (é código pequeno e testado fora do Docker).
5. Valide (substitua U/P pelos do `.env`), imprimindo só tamanhos/contagens:
   - `curl -s http://localhost:8080/health` → `{"ok": true, ...}`
   - `curl -s "http://localhost:8080/player_api.php?username=U&password=P"` → `"auth": 1`
   - `curl -s "http://localhost:8080/player_api.php?username=U&password=P&action=get_series_categories" | head -c 300`
   - senha errada deve dar HTTP 401.
6. Descubra o IP do PC na rede local (`ipconfig` no Windows / `ip a` no Linux / `ifconfig` no Mac) e
   entregue ao dono, pronto para colar no HM IPTV:
   - tipo: **Xtream Codes**, servidor `http://IP_DO_PC:8080`, usuário e senha do `.env`.
   - celular e PC no mesmo Wi-Fi. Se não conectar: firewall do PC liberando a porta 8080 (Windows:
     "Permitir um aplicativo" / regra de entrada TCP 8080).
7. Orientação para o dono: se o HM IPTV travar ao carregar tudo, usar as categorias; alternativa no
   app é cadastrar como M3U filtrado: `http://IP:8080/get.php?username=U&password=P&type_filter=live`
   (`live`, `movie` ou `episode`; `&category=Nome` filtra por categoria).

## Sincronizar com o repositório original
O original é **https://github.com/Ramys/Iptv-Brasil-2026** (branch `master`). Este repositório é uma cópia
dele (não é fork oficial do GitHub, por isso a sincronização copia arquivos em vez de fazer merge).
Já está configurado como padrão no workflow — **não é preciso criar variável nenhuma**.
1. O workflow só roda quando estiver na `master`: o dono precisa fazer o **merge da `xtream-server` na
   `master`** (Pull Request no GitHub). Avise que, na primeira sincronização, arquivos que existem só neste
   repositório e não no original **serão apagados** (exceto `server/`, `scripts/`, `docker-compose.yml`,
   `.env.example`, `.gitignore`, `LEIAME-SERVIDOR.md`, `INSTRUCOES-CLAUDE.md`, `.github/workflows/`).
   Na data da configuração, a estrutura de arquivos do original era idêntica à deste repositório.
2. Teste: *Actions → Sincronizar com o repositório original → Run workflow*. Deve terminar verde.
3. Sincronização manual no PC: `scripts/sync-upstream.sh Ramys/Iptv-Brasil-2026 master`.
4. O container já faz `git pull` sozinho a cada 6 h (`GIT_PULL_INTERVAL_MIN`) e reindexa quando as
   listas mudam; para forçar: `docker compose restart`.
5. Limite do GitHub: 100 MB por arquivo. As maiores listas do original têm ~94 MB; se o original
   passar de 100 MB, o push da sincronização falha — avise o dono.

## Tudo gratuito — opções e limites honestos
| Necessidade | Opção gratuita | Observação / risco |
|---|---|---|
| Rodar o servidor | O **próprio PC** com Docker Desktop | Grátis. Só funciona com o PC ligado. É a opção recomendada. |
| Acesso fora de casa | **Tailscale** (plano pessoal gratuito) no PC e no iPhone | Evita abrir porta no roteador. Configurar usa a conta do dono. Use o IP/nome Tailscale no lugar de `IP_DO_PC`. |
| Rodar 24 h sem o PC | **Oracle Cloud Always Free** (VM ARM) | Pelo que se sabe, exige cadastro com cartão (sem cobrança no plano gratuito) e a disponibilidade de VMs varia; as condições podem ter mudado — confirme na página oficial antes de prometer. Mesmos comandos do PC. |
| Sincronização | **GitHub Actions** | Gratuito para repositório público (limite mensal generoso). Nada a pagar. |
| Hospedar as listas | O próprio repositório no GitHub | Limite de 100 MB por arquivo; as listas atuais têm até ~94 MB — se o original crescer além disso, o push falha. Avise o dono se isso acontecer. |

Evite: VPS/hospedagens "grátis" desconhecidas, que pedem dados de pagamento ou rodam em PaaS com
suspensão automática; elas não aguentam um índice desse tamanho e o dono pode ser lesado.

## Se algo der errado — checklist rápido
- `503 Indexando...`: aguarde ~15–60 s e consulte `docker compose logs`.
- App não conecta: IP errado, PC e celular em redes diferentes, ou firewall bloqueando a 8080.
- `401`: usuário/senha diferentes do `.env`; após editar o `.env`, `docker compose up -d` de novo.
- Catálogo antigo: `docker compose restart` (reindexa se as listas mudaram).
- Canais/filmes não tocam mas o catálogo aparece: os links de dentro das listas são de terceiros e
  podem estar fora do ar; o servidor só organiza e redireciona. Não é falha do servidor.
- Disco/RAM: o índice SQLite fica no volume `xtream-db` (centenas de MB); pode ser apagado, recria sozinho.

## O que reportar ao dono no final
Diga em poucas linhas: o que funcionou, o que não foi testado, o endereço/usuário para colocar no
HM IPTV, e o que ainda depende dele (fazer o merge na `master`).
