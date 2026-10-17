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

say ""
say "=============================================================="
say " SECTION 1 — GGTT: where the page tables live (BAR0 window)"
say "=============================================================="
# The GGTT (global GTT) entry array lives in an MMIO window inside BAR0; the
# probe code computes/derives its offset. This is the lookup D1 depends on.
if [ "${#SRC[@]}" -gt 0 ]; then
  grep -nH -E "gtt_base|GTT_BASE|GTT_OFFSET|gtt_offset|0x800000|ggtt->regs|ggtt->gsm" "${SRC[@]}" 2>/dev/null \
    | head -n 60 | tee -a "$EX" || true
fi

if [ -f "$OUT/intel_ggtt.c" ]; then
  say ""
  say "--- intel_ggtt.c: probe functions (definition heads)"
  grep -nH -E "^static.*(probe|setup)|^int intel_ggtt|^void intel_ggtt" "$OUT/intel_ggtt.c" 2>/dev/null \
    | head -n 40 | tee -a "$EX" || true
fi

say ""
say "=============================================================="
say " SECTION 2 — PTE encoding (what a GGTT entry looks like)"
say "=============================================================="
if [ -f "$OUT/gen8_ppgtt.c" ]; then
  say "--- gen8_pte_encode: every mention + context (gen8_ppgtt.c)"
  grep -nH -A35 "gen8_pte_encode" "$OUT/gen8_ppgtt.c" 2>/dev/null \
    | head -n 200 | tee -a "$EX" || true
fi

say ""
say "--- PTE/PDE flag definitions (all fetched files)"
if [ "${#SRC[@]}" -gt 0 ]; then
  grep -nH -E "_PAGE_PRESENT|_PAGE_RW|PPAT_|PAT_INDEX|GEN12_PPGTT_PTE|GEN8_PDE_" "${SRC[@]}" 2>/dev/null \
    | head -n 80 | tee -a "$EX" || true
fi

say ""
say "=============================================================="
say " SECTION 3 — GGTT object layouts (what IXRM must mirror)"
say "=============================================================="
if [ -f "$OUT/intel_gtt.h" ]; then
  say "--- struct i915_ggtt (intel_gtt.h)"
  grep -nH -A16 "struct i915_ggtt {" "$OUT/intel_gtt.h" 2>/dev/null \
    | head -n 40 | tee -a "$EX" || true
  say ""
  say "--- PTE read/write helpers (intel_gtt.h)"
  grep -nH -B1 -A12 -E "write_pte|read_pte|ggtt_get_pte|ggtt->vm.pt" "$OUT/intel_gtt.h" 2>/dev/null \
    | head -n 60 | tee -a "$EX" || true
fi

# --- fact summary (quick scan for the CI log) ---------------------------------
say ""
say "== key-fact hit counts (0 = file moved; see MISS list above)"
for pat in "gtt_offset|gtt_base|GTT_BASE" "0x800000" "gen8_pte_encode" "_PAGE_PRESENT"; do
  n="$(grep -chE "$pat" "${SRC[@]}" 2>/dev/null | awk '{s+=$1} END {print s+0}' || true)"
  say "  $pat: $n"
done

say ""
say "== extract written to $EX ($(wc -c < "$EX") bytes)"
