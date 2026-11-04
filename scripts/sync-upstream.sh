#!/usr/bin/env bash
# Traz para este repositorio o conteudo do repositorio original ("upstream"),
# sem tocar nos arquivos do servidor. Funciona mesmo que os historicos sejam diferentes
# (copia o estado dos arquivos em vez de fazer merge).
#
# Uso: scripts/sync-upstream.sh <dono/repo | url> [branch]
set -euo pipefail

UP="${1:?informe o repositorio original: dono/repo ou URL}"
BRANCH="${2:-}"
case "$UP" in
  http*|git@*|/*|./*|../*) URL="$UP" ;;
  *) URL="https://github.com/$UP.git" ;;
esac

# Arquivos que sao NOSSOS e nunca sao sobrescritos/apagados pelo upstream.
OWN='^(server/|scripts/|docker-compose\.yml$|\.env\.example$|\.gitignore$|LEIAME-SERVIDOR\.md$|\.github/workflows/)'

git remote remove upstream 2>/dev/null || true
git remote add upstream "$URL"
if [ -z "$BRANCH" ]; then
  BRANCH="$(git ls-remote --symref upstream HEAD | awk '/^ref:/{sub("refs/heads/","",$2); print $2; exit}')"
fi
git fetch --depth 1 upstream "$BRANCH"
UPREF=FETCH_HEAD

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git ls-tree -r --name-only "$UPREF" | grep -Ev "$OWN" | sort > "$TMP/up"   || true
git ls-files                         | grep -Ev "$OWN" | sort > "$TMP/mine" || true

# 1) copia/atualiza tudo que o upstream tem
if [ -s "$TMP/up" ]; then
  tr '\n' '\0' < "$TMP/up" | xargs -0 git checkout "$UPREF" --
fi
# 2) remove o que o upstream apagou
comm -13 "$TMP/up" "$TMP/mine" > "$TMP/gone"
if [ -s "$TMP/gone" ]; then
  tr '\n' '\0' < "$TMP/gone" | xargs -0 git rm -q --
fi

git add -A
if git diff --cached --quiet; then
  echo "Ja esta igual ao upstream ($URL @ $BRANCH)."
  exit 0
fi
git -c user.name="sync-upstream" -c user.email="sync-upstream@users.noreply.github.com" \
  commit -q -m "Sincroniza com o upstream ($UP @ $BRANCH)"
echo "Sincronizado com $UP @ $BRANCH."
echo "changed=true"
