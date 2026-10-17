#!/usr/bin/env bash
# ixgen — fetch the pinned i915 reference facts our IXRM bring-up is built on,
# and extract the sections each stage needs into a provenance-stamped text file.
#
# Why this exists: the project rule is "never guess a register value". Every
# hardware fact IXRM will use (GGTT window location, PTE encoding, flag bits,
# ...) must be traceable to a pinned upstream source. This script is that
# source pipeline. It runs in GitHub CI; the job log and the small extract
# artifact ARE the audit trail. Nothing fetched here is committed to the tree.
#
# The pinned tag matches the kernel the first real hardware capture came from
# (Kali 6.12 on the Latitude 5420), so plan, capture and facts all agree.
#
# v2 (2026-10-17): after the first run, print whole function bodies
#   (ggtt_probe_common, gen8_gmch_probe, ggtt_probe_hw, both pte encoders) and
#   anchored #define lines, so formulas AND values come out in one run.
#
# Usage:  bash tools/ixgen/fetch_i915.sh [TAG] [OUTDIR]
#         (defaults: v6.12, i915-ref/)
set -euo pipefail

TAG="${1:-v6.12}"
OUT="${2:-i915-ref}"
BASE="https://raw.githubusercontent.com/torvalds/linux/$TAG"
EX="$OUT/extract.txt"

mkdir -p "$OUT"
: > "$EX"

# curl with the CI token when present (raises API rate limits; harmless for raw)
AUTH=()
if [ -n "${GITHUB_TOKEN:-}" ]; then AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN"); fi

say() { printf '%s\n' "$@" | tee -a "$EX"; }

# The files each IXRM stage reads. The kernel tree moves files around between
# releases, so we try a candidate list, report OK/MISS for every entry, and let
# the log be the map. A MISS is information, not a failure.
FILES="
drivers/gpu/drm/i915/i915_reg.h
drivers/gpu/drm/i915/gt/intel_gt_regs.h
drivers/gpu/drm/i915/gt/intel_ggtt.c
drivers/gpu/drm/i915/gt/gen8_ppgtt.c
drivers/gpu/drm/i915/gt/gen8_ppgtt.h
drivers/gpu/drm/i915/gt/intel_gtt.h
drivers/gpu/drm/i915/gt/intel_gtt.c
drivers/gpu/drm/i915/gt/intel_ggtt_gmch.c
"

say "== ixgen: i915 hardware-facts pipeline"
say "# tag:     $TAG"
say "# base:    $BASE"
say "# fetched: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
if command -v jq >/dev/null 2>&1; then
  SHA="$(curl -fsSL "${AUTH[@]}" "https://api.github.com/repos/torvalds/linux/commits/$TAG" 2>/dev/null \
         | jq -r '.sha // empty' 2>/dev/null || true)"
  if [ -n "${SHA:-}" ]; then say "# commit:  $SHA  (tag $TAG resolves to this)"; fi
fi

say ""
say "== fetching"
fetched=0
for f in $FILES; do
  dest="$OUT/$(basename "$f")"
  if curl -fsSL --retry 3 --retry-delay 2 "${AUTH[@]}" "$BASE/$f" -o "$dest" 2>/dev/null; then
    say "OK   $f  ($(wc -c < "$dest") bytes)"
    fetched=$((fetched + 1))
  else
    say "MISS $f"
    rm -f "$dest"
  fi
done
if [ "$fetched" -eq 0 ]; then
  say "ERROR: nothing fetched — wrong tag, or network is down" >&2
  exit 1
fi

# Best-effort layout aid: if some paths moved, the directory listing shows where.
if command -v jq >/dev/null 2>&1; then
  say ""
  say "== drivers/gpu/drm/i915 top level (what actually exists at this tag)"
  curl -fsSL "${AUTH[@]}" "https://api.github.com/repos/torvalds/linux/contents/drivers/gpu/drm/i915?ref=$TAG" 2>/dev/null \
    | jq -r '.[]? | "\(.type)\t\(.size)\t\(.name)"' 2>/dev/null | head -n 60 || true
fi

# --- extraction helpers -------------------------------------------------------
# Files fetched this run (extract.txt and listing are deliberately not globbed).
SRC=()
for f in "$OUT"/*.c "$OUT"/*.h; do
  if [ -e "$f" ]; then SRC+=("$f"); fi
done

search() { # search <limit> <pattern> <files...>
  local limit="$1" pat="$2"; shift 2
  grep -nH -E "$pat" "$@" 2>/dev/null | head -n "$limit" | tee -a "$EX" || true
}

fnbody() { # fnbody <file> <start-regex> <limit> — whole function body, no cuts
  local file="$1" pat="$2" limit="$3"
  [ -f "$file" ] || return 0
  awk -v pat="$pat" -v limit="$limit" '
    $0 ~ pat { f=1 }
    f { printf "%s:%d:%s\n", FILENAME, FNR, $0 }
    f && (/^}/ || n++ >= limit) { exit }
  ' "$file" | tee -a "$EX" || true
}

say ""
say "=============================================================="
say " SECTION 1 — GGTT: where the page tables live (and how they map)"
say "=============================================================="
if [ "${#SRC[@]}" -gt 0 ]; then
  search 60 "gtt_base|GTT_BASE|GTT_OFFSET|gtt_offset|ggtt->gsm|0x800000" "${SRC[@]}"
fi

say ""
say "--- ggtt_probe_common(): the mapping and where phys_addr comes from"
fnbody "$OUT/intel_ggtt.c" "ggtt_probe_common" 100

say ""
say "--- gen8_gmch_probe(): GTT size derivation"
fnbody "$OUT/intel_ggtt.c" "gen8_gmch_probe" 100

say ""
say "--- ggtt_probe_hw()"
fnbody "$OUT/intel_ggtt.c" "ggtt_probe_hw" 60

say ""
say "--- resource/phys_addr/mappable mentions (intel_ggtt.c)"
search 40 "phys_addr|pci_resource_len|pci_resource_start|mappable_end|vm\.total" "$OUT/intel_ggtt.c"

say ""
say "=============================================================="
say " SECTION 2 — PTE encoding (what a GGTT entry looks like)"
say "=============================================================="
say "--- gen8_pte_encode(): whole body"
fnbody "$OUT/gen8_ppgtt.c" "static u64 gen8_pte_encode" 40

say ""
say "--- gen12_pte_encode(): whole body (Tiger Lake is gen12)"
fnbody "$OUT/gen8_ppgtt.c" "static u64 gen12_pte_encode" 40

say ""
say "--- which encoder the GGTT itself uses"
search 30 "pte_encode" "$OUT/intel_ggtt.c" "$OUT/gen8_ppgtt.c" "$OUT/intel_gtt.h"

say ""
say "--- anchored #define lines: the numeric values (all fetched files)"
if [ "${#SRC[@]}" -gt 0 ]; then
  search 160 "^#define[[:space:]]+(GEN8_PAGE|PPAT_|GEN12_PPGTT_PTE|GEN8_PDE|PTE_|I915_GTT_PAGE|_PAGE_|PHYSICAL)" "${SRC[@]}"
fi

say ""
say "--- pte_t typedefs (entry width)"
if [ "${#SRC[@]}" -gt 0 ]; then
  search 20 "typedef.*pte_t" "${SRC[@]}"
fi

say ""
say "--- addresses masks / GENMASK use in entry setup"
search 40 "ADDR_MASK|GENMASK" "$OUT/gen8_ppgtt.c" "$OUT/intel_ggtt.c"

say ""
say "=============================================================="
say " SECTION 3 — GGTT object layouts (what IXRM must mirror)"
say "=============================================================="
say "--- struct i915_ggtt (intel_gtt.h)"
fnbody "$OUT/intel_gtt.h" "struct i915_ggtt {" 40

say ""
say "--- PTE array access patterns + index math (intel_ggtt.c)"
search 50 "gsm \\+|first_entry|I915_GTT_PAGE_SIZE" "$OUT/intel_ggtt.c"

# --- fact summary (quick scan for the CI log) ---------------------------------
say ""
say "== key-fact hit counts (0 = file moved; see MISS list above)"
for pat in "gtt_offset|gtt_base|GTT_BASE" "0x800000" "gen8_pte_encode" "gen12_pte_encode" \
           "GEN8_PAGE_PRESENT" "PPAT_|GEN12_PPGTT_PTE" "pci_resource_len"; do
  n="$(grep -chE "$pat" "${SRC[@]}" 2>/dev/null | awk '{s+=$1} END {print s+0}' || true)"
  say "  $pat: $n"
done

say ""
say "== extract written to $EX ($(wc -c < "$EX") bytes)"
