#!/bin/bash
# Costruisce ResolveToolkit-<versione>.pkg anche da Linux (xar + mkbom), senza bisogno di un Mac.
# Uso: installer/costruisci_pkg.sh <percorso xar> <percorso mkbom>
set -euo pipefail

XAR="${1:-xar}"
MKBOM="${2:-mkbom}"
RADICE="$(cd "$(dirname "$0")/.." && pwd)"
VERSIONE=$(grep '^version' "$RADICE/pyproject.toml" | cut -d'"' -f2)
ID="it.colucci.resolvetoolkit"
DEST_INSTALL="/Library/Application Support/ResolveToolkit"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# contenuto installato in /Library/Application Support/ResolveToolkit/src
mkdir -p "$TMP/root/src" "$TMP/scripts" "$TMP/flat/base.pkg"
cp -R "$RADICE/src" "$RADICE/pyproject.toml" "$RADICE/README.md" "$RADICE/installer" "$TMP/root/src/"
find "$TMP/root" -name __pycache__ -prune -exec rm -rf {} +
find "$TMP/root" -name "*.egg-info" -prune -exec rm -rf {} +
cp "$RADICE/installer/scripts/postinstall" "$TMP/scripts/postinstall"
chmod 755 "$TMP/scripts/postinstall"
find "$TMP/root" -type d -exec chmod 755 {} +
find "$TMP/root" -type f -exec chmod 644 {} +

N_FILE=$(find "$TMP/root" | wc -l | tr -d ' ')
KB=$(du -sk "$TMP/root" | cut -f1)

( cd "$TMP/root" && find . | cpio -o --quiet --format odc --owner 0:80 | gzip -c ) > "$TMP/flat/base.pkg/Payload"
( cd "$TMP/scripts" && find . | cpio -o --quiet --format odc --owner 0:80 | gzip -c ) > "$TMP/flat/base.pkg/Scripts"
"$MKBOM" -u 0 -g 80 "$TMP/root" "$TMP/flat/base.pkg/Bom"

cat > "$TMP/flat/base.pkg/PackageInfo" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<pkg-info format-version="2" identifier="$ID" version="$VERSIONE" install-location="$DEST_INSTALL" auth="root">
  <payload installKBytes="$KB" numberOfFiles="$N_FILE"/>
  <scripts>
    <postinstall file="./postinstall"/>
  </scripts>
</pkg-info>
EOF

cat > "$TMP/flat/Distribution" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="1">
  <title>Resolve Toolkit $VERSIONE</title>
  <options customize="never" require-scripts="false" hostArchitectures="x86_64,arm64"/>
  <domains enable_localSystem="true"/>
  <choices-outline>
    <line choice="$ID"/>
  </choices-outline>
  <choice id="$ID" title="Resolve Toolkit">
    <pkg-ref id="$ID"/>
  </choice>
  <pkg-ref id="$ID" installKBytes="$KB" version="$VERSIONE" auth="Root">#base.pkg</pkg-ref>
</installer-gui-script>
EOF

USCITA="$RADICE/ResolveToolkit-$VERSIONE.pkg"
( cd "$TMP/flat" && "$XAR" --compression none -cf "$USCITA" * )
echo "$USCITA"
