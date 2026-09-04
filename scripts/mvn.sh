#!/bin/sh
# The only sanctioned way to run Maven in this repo.
#
# Homebrew's maven pulls JDK 26 as a dependency and uses it by default, ahead of
# whatever is on PATH. Lombok and Spring plugins break on a JDK that new and the
# failure is cryptic. JDK 21 at this path is keg-only, so it shadows nothing.
set -eu

JDK21=/opt/homebrew/opt/openjdk@21
if [ ! -x "$JDK21/bin/java" ]; then
  echo "JDK 21 not found at $JDK21 — install it: brew install openjdk@21" >&2
  exit 1
fi

JAVA_HOME="$JDK21"
export JAVA_HOME
exec mvn -f "$(dirname "$0")/../service/pom.xml" "$@"
