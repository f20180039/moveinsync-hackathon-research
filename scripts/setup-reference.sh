#!/usr/bin/env bash
# Clone the 8 reference repos analysed in specs/ into reference/.
#
# They are deliberately NOT vendored in this repo: 3 of the 8 declare no licence,
# so their source is not ours to redistribute. Every spec cites file:line against
# the exact clone strategies below (note the sparse checkouts — FleetPy is 662 MB
# whole and 4.9 MB sparse).
#
# Usage:  ./scripts/setup-reference.sh            # clone everything (~29 MB)
#         ./scripts/setup-reference.sh pyvrp vroom  # clone only these keys
#
# Idempotent: an existing directory is skipped, not re-cloned.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
mkdir -p reference && cd reference || exit 1

# key|url|dirname|sparse-paths (empty = full clone)
REPOS=(
  "bengaluru-metro-dataset|https://github.com/Vinayak-Chinchakhandi/Bengaluru-Metro-Network-Dataset|bengaluru-metro-dataset|"
  "smart-airport-cabpooling|https://github.com/maheshwarisharman/smart-aiport-cabpooling-backend|smart-aiport-cabpooling-backend|"
  "vroom|https://github.com/VROOM-Project/vroom|vroom|"
  "pyvrp|https://github.com/PyVRP/PyVRP|pyvrp|"
  "rideshare-optimizer|https://github.com/ashhwiithac22/RideShare-Optimizer|RideShare-Optimizer|"
  "car-pooling-mern|https://github.com/LohithMarneni/Car-Pooling-System|Car-Pooling-System|"
  "fleetpy|https://github.com/TUM-VT/FleetPy|fleetpy|src docs examples"
  "timefold-quickstarts|https://github.com/TimefoldAI/timefold-quickstarts|timefold-quickstarts|use-cases/vehicle-routing use-cases/employee-scheduling"
)

want=("$@")
selected() {
  [ ${#want[@]} -eq 0 ] && return 0
  for w in "${want[@]}"; do [ "$w" = "$1" ] && return 0; done
  return 1
}

ok=0; skip=0; fail=0
for entry in "${REPOS[@]}"; do
  IFS='|' read -r key url dir sparse <<<"$entry"
  selected "$key" || continue

  if [ -d "$dir" ]; then
    printf '  skip     %-38s (already present)\n' "$key"; skip=$((skip+1)); continue
  fi

  if [ -n "$sparse" ]; then
    # shellcheck disable=SC2086
    if git clone --depth 1 --filter=blob:none --sparse -q "$url.git" "$dir" 2>/dev/null \
       && git -C "$dir" sparse-checkout set $sparse 2>/dev/null; then
      printf '  cloned   %-38s (sparse: %s)\n' "$key" "$sparse"; ok=$((ok+1))
    else
      printf '  FAILED   %-38s %s\n' "$key" "$url"; fail=$((fail+1))
    fi
  else
    if git clone --depth 1 -q "$url.git" "$dir" 2>/dev/null; then
      printf '  cloned   %-38s\n' "$key"; ok=$((ok+1))
    else
      printf '  FAILED   %-38s %s\n' "$key" "$url"; fail=$((fail+1))
    fi
  fi
done

echo
echo "  cloned $ok, skipped $skip, failed $fail  ->  $(du -sh . 2>/dev/null | cut -f1) in reference/"
echo "  next: read specs/INDEX.md"
[ "$fail" -eq 0 ] || exit 1
