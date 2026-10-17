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
# v3 (2026-10-17): v2 located the GGTT mapping and the entry bit values; v3
#   printed the functions behind the remaining unknowns (gen6_gttadr_offset,
#   gen6_gttmmadr_size, gen8_get_total_gtt_size, gen8_ggtt_pte_encode,
#   gen8_ggtt_insert_entries, gen8_set_pte) with signature patterns (v2's
#   ggtt_probe_common pattern first hit a comment mention), fetched the x86 PTE
#   header for the _PAGE_* bits PPAT_* is built from, and survives raw.github
#   flaking (--retry-all-errors; i915_reg.h missed v2 for unrelated reasons).
#
# v4 (2026-10-17): D1 landed on the v3 facts; v4 completes the sheet for D2 —
#   the GMCH/GGMS decode constants (real GTT table size), SZ_* via
#   include/linux/sizes.h, and i915_direct_stolen_access() to confirm TGL takes
#   the BAR window path (not the GSMBASE one).
#
# v5 (2026-10-17): v4 lost five files to raw.githubusercontent 429s, so v5 adds
#   a fallback fetch route (the authenticated contents API, raw media type).
#   The GMCH/GGMS defines turned out to live in include/drm/intel/i915_drm.h at
#   v6.12 (not i915_reg.h), and i915_direct_stolen_access() in i915_utils.{c,h}
#   — both are now fetch targets, and the direct-stolen section prints every
#   call site.
#
# v6 (2026-10-17): two extraction lessons from the v5 log. (1) The runner's awk
#   rejects an escaped paren in fnbody patterns: "awk: warning: escape sequence
#   `\(' treated as plain `('" followed by "fatal: invalid regexp: Unmatched ( or
#   \(" — an empty body that still looked like success. Patterns here stay
#   escape-free; where a symbol repeats, file order (.c first) picks the
#   definition. (2) The GMCH/GGMS defines sit behind SNB_/BDW_ prefixes that the
#   anchored #define alternation cannot catch, so they get a targeted per-file
#   search of i915_drm.h instead.
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
drivers/gpu/drm/i915/i915_drv.h
drivers/gpu/drm/i915/i915_utils.c
drivers/gpu/drm/i915/i915_utils.h
arch/x86/include/asm/pgtable_types.h
include/linux/sizes.h
include/drm/intel/i915_drm.h
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
# Two routes: raw.githubusercontent (fast, unauthenticated — but it can 429 on
# busy CI egress IPs) and, as a fallback, the authenticated contents API with
# the raw media type. v4 lost five files on route 1 alone; route 2 keeps the
# fact sheet whole.
fetch_one() { # fetch_one <repo-path> <dest>
  local path="$1" dest="$2"
  if curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors "$BASE/$path" -o "$dest" 2>/dev/null; then
    return 0
  fi
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -fsSL "${AUTH[@]}" -H "Accept: application/vnd.github.raw" \
      "https://api.github.com/repos/torvalds/linux/contents/$path?ref=$TAG" -o "$dest" 2>/dev/null
  fi
}
fetched=0
for f in $FILES; do
  dest="$OUT/$(basename "$f")"
  if fetch_one "$f" "$dest"; then
    say "OK   $f  ($(wc -c < "$dest") bytes)"
    fetched=$((fetched + 1))
  else
    say "MISS $f"
    rm -f "$dest"
  fi
  sleep 1   # be gentle with raw.githubusercontent rate limits
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

fnbody_any() { # fnbody_any <start-regex> <limit> — first fetched file containing it
  local pat="$1" limit="$2" f
  for f in "${SRC[@]}"; do
    [ -e "$f" ] || continue
    if grep -qE "$pat" "$f" 2>/dev/null; then
      fnbody "$f" "$pat" "$limit"
      return 0
    fi
  done
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
fnbody "$OUT/intel_ggtt.c" "static int ggtt_probe_common" 110

say ""
say "--- gen8_gmch_probe(): GTT size derivation"
fnbody "$OUT/intel_ggtt.c" "static int gen8_gmch_probe" 100

say ""
say "--- ggtt_probe_hw()"
fnbody "$OUT/intel_ggtt.c" "static int ggtt_probe_hw" 60

say ""
say "--- gen6_gttadr_offset() / gen6_gttmmadr_size(): where in the BAR the GGTT lives"
fnbody_any "gen6_gttadr_offset" 40
fnbody_any "gen6_gttmmadr_size" 40

say ""
say "--- i915_direct_stolen_access(): which phys_addr path applies on TGL"
fnbody_any "i915_direct_stolen_access" 30
search 20 "direct_stolen" "${SRC[@]}"

say ""
say "--- gen8_get_total_gtt_size(): decoding SNB_GMCH_CTRL"
fnbody_any "gen8_get_total_gtt_size" 60

say ""
say "--- GMCH/GGMS defines (i915_drm.h): SNB_/BDW_ prefixes defeat the anchored search"
if [ -f "$OUT/i915_drm.h" ]; then
  search 60 "GMCH_CTRL|GMCH_GGMS|GMCH_GMS" "$OUT/i915_drm.h"
fi

say ""
say "--- searches: BAR offsets, GSM base, GTT size, entry address mask"
search 60 "gttadr|gttmmadr|GSMBASE|BDSM|GMCH_CTRL|SNB_GMCH|GEN12_GGTT_PTE_ADDR_MASK" "${SRC[@]}"

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
say "--- gen8_ggtt_pte_encode() — the GGTT encoder on gen12 < 12.70 (Tiger Lake)"
fnbody "$OUT/intel_ggtt.c" "u64 gen8_ggtt_pte_encode" 50

say ""
say "--- mtl_ggtt_pte_encode() (12.70+, for contrast)"
fnbody "$OUT/intel_ggtt.c" "static u64 mtl_ggtt_pte_encode" 40

say ""
say "--- gen8_ggtt_insert_entries() — the bulk write path"
fnbody "$OUT/intel_ggtt.c" "gen8_ggtt_insert_entries" 70

say ""
say "--- small helpers: gen8_set_pte, ggtt_total_entries, needs_wc_ggtt_mapping"
fnbody_any "gen8_set_pte" 25
fnbody_any "ggtt_total_entries" 20
fnbody_any "needs_wc_ggtt_mapping" 25

say ""
say "--- anchored #define lines: the numeric values (all fetched files)"
if [ "${#SRC[@]}" -gt 0 ]; then
  search 200 "^#define[[:space:]]+(GEN8_PAGE|PPAT_|GEN12_PPGTT|GEN12_GGTT|GEN8_PDE|PTE_|I915_GTT_PAGE|_PAGE_|PHYSICAL|BDSM|GMCH|GGMS|SZ_|HAS_LMEM)" "${SRC[@]}"
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
           "GEN8_PAGE_PRESENT" "PPAT_|GEN12_PPGTT_PTE" "pci_resource_len" \
           "gen8_ggtt_pte_encode" "gttadr"; do
  n="$(grep -chE "$pat" "${SRC[@]}" 2>/dev/null | awk '{s+=$1} END {print s+0}' || true)"
  say "  $pat: $n"
done

say ""
say "== extract written to $EX ($(wc -c < "$EX") bytes)"
