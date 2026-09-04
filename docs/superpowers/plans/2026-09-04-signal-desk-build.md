# Signal Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an agent that sweeps enterprise commute data without being asked, ranks what a transport manager needs to know, and delivers it to Slack and email with the reasoning and the originating SQL attached.

**Architecture:** Four layers with one hard seam. Ingest loads six CSV feeds into embedded DuckDB tolerantly and quarantines what it cannot parse; a metric registry is the only thing that queries tables; pure rules compare each metric against its reference points and emit ranked `Finding` records; the model turns settled findings into prose and answers questions through four validated tools. Nothing arithmetic passes through the model.

**Tech Stack:** Java 21 · Spring Boot 3.5 · DuckDB JDBC (embedded) · OpenAI Java SDK against Sarvam · AWS SDK v2 (SES) · React 19 · Vite 7 · TypeScript · Recharts · JUnit 5 + AssertJ · Vitest + Testing Library

**Spec:** [`docs/superpowers/specs/2026-09-04-signal-desk-design.md`](../specs/2026-09-04-signal-desk-design.md) — read it alongside this plan. Where the two disagree the spec wins, except for the deviations recorded below, which were resolved deliberately.

**Authority above both:** [`docs/MoveInSync-problem-statement.pdf`](../../MoveInSync-problem-statement.pdf).

---

## Global Constraints

Every task's requirements implicitly include this section.

- **JDK 21 only.** `export JAVA_HOME=/opt/homebrew/opt/openjdk@21` before any `mvn` invocation. Homebrew's Maven pulls JDK 26 and prefers it; Lombok and Spring plugins break on it with cryptic errors. `mvn -v` must report 21.
- **Node 22.** Pinned by `.nvmrc`; run `nvm use` on entering the repo. The global default is deliberately 18 for other projects on this machine — never change it. Vite 7 requires Node 20.19+ or 22.12+.
- **`engine-strict=true`** is already set in `.npmrc` and gates `npm install`. It does nothing for `npm run`, so `scripts/require-node.mjs` must be wired as the console's `predev` script.
- **`ignore_errors` is forbidden** in every `read_csv_auto` call. It has a known defect that silently drops *valid* rows. Use `store_rejects = true` and read the rejects back.
- **The model never computes a number and never writes raw SQL.** No `run_sql` tool exists at any point. If a change would let a model-produced figure reach a screen, the change is wrong.
- **Tiers are ordinal and are never summed.** Three `WATCH`es must never outrank one `BREACH`.
- **Golden thresholds are measured, then pinned** — never invented. Land each golden assertion first as "greater than zero" with the real value logged, then pin at ~80% of what was measured, recording the measurement in a comment.
- **Break-it-to-prove-it on every guard.** After a test passes, delete the behaviour it is named for, confirm the test fails, restore. Steps below name this explicitly where it matters most; apply it everywhere regardless. See [`docs/TESTING-LESSONS.md`](../../TESTING-LESSONS.md).
- **A test name claiming a general property** ("never", "always", "scales", "is deterministic") needs two or more data points, or it must be renamed to the single case it actually asserts.
- **Secrets live in environment variables only:** `SARVAM_API_KEY`, `SLACK_WEBHOOK_URL`, `SES_FROM`, `SES_TO`. A Slack webhook URL is itself a credential. Nothing credential-shaped reaches a commit, a screenshot, a log line, or the deck. Every new variable gets a placeholder entry in the committed example-env file.
- **Model:** `sarvam-105b` at base URL `https://api.sarvam.ai/v1`, auth `Authorization: Bearer <key>`. Sarvam-M is deprecated and no longer served.
- **Determinism:** the fixture generator takes a fixed seed and produces byte-identical output. No `Math.random()`, no `System.currentTimeMillis()`, no wall-clock reads anywhere in the sweep path. The sweep reads an injected `java.time.Clock`.
- **Money is integer rupees. Durations are minutes. Distances are kilometres. Timestamps are epoch milliseconds.**
- **Commit after every task**, with the message given in the task's final step.

---

## Preflight — verify before Task 1

These are the proposal's "do these tonight" items. Two are reported done; confirm the rest, because three tasks below cannot complete without them.

- [ ] `export JAVA_HOME=/opt/homebrew/opt/openjdk@21 && mvn -v` reports **Java 21** (not 22, not 26)
- [ ] `nvm use && node -v` reports **v22.x**
- [ ] `duckdb -c "SELECT version();"` runs, and `ls ~/.duckdb/extensions/` shows a cached `httpfs`
- [ ] `SARVAM_API_KEY` is exported, and one real call to `sarvam-105b` with a `tools` array returned `finish_reason: "tool_calls"` — **reported done; if it was not, do it now, not at Task 22.** The interrogation panel cannot be built without it, and it is the one capability whose absence changes the plan.
- [ ] `SLACK_WEBHOOK_URL` is exported and a `curl` post to it appears in the channel — **Task 11 is blocked without this, and Task 11 is inside the protected slice.**
- [ ] 2–3 team email addresses are verified in AWS SES sandbox — Task 14 is blocked without this. Not needed before the checkpoint.
- [ ] Repo collaborators added (owner `@f20180039`), AWS budgets set in the console — both outstanding, neither blocks code.
- [ ] `docker --version` runs and the daemon is up — **Task 16 is blocked without it.** Not needed before Task 16.
- [ ] A Render account exists and can see this repo — **Task 16 Step 9 is blocked without it.** The repo is private, so Render needs the GitHub authorisation granted.
- [ ] The Render account can create a **static site** as well as a web service (both are free tier) — **Task 19 is blocked without it.** No Vercel account is needed: both surfaces are on Render.

The last three are the only preflight items added by the deployment tasks. None of
them blocks Phase 1, so they can be sorted out while the protected slice is being
built — but sort them out *then*, not at Task 16, because a Render authorisation
on a private repo has occasionally needed an owner to approve it.

If the Slack webhook is not ready at Task 11, implement `SlackChannel` against a local HTTP stub, keep the suite green, and mark the checkpoint demo as *unproven on the real channel*. Do not fake a screenshot.

---

## Spec deviations and resolved ambiguities

Reading the spec closely enough to write executable tasks surfaced eight places where it is silent, self-contradictory, or would not compile. Each is resolved here rather than left to whoever picks up the task. **If the team disagrees with any of these, change it here before execution starts, not mid-build.**

1. **`Finding.gap` sign — the spec contradicts itself.** §6.2 says `gap` is "signed: observed − the reference that fired". §6.3 says `gap` is `delta × reference`, and for a HIGHER-is-better metric `delta × reference = reference − observed` — the opposite sign. **Resolution: §6.3 wins.** `gap = delta * reference`, so **positive always means worse**, for both metric directions, and the sign agrees with the tier by construction. §6.2's comment is superseded. A test asserts the agreement.

2. **"A TARGET missed outright → BREACH" would make WATCH and CONCERN unreachable for every TARGET metric.** Read literally, any shortfall against a target breaches and the delta bands never apply to `ota` or `sla_breach`. **Resolution:** the phrase covers targets that admit no tolerance. `Metric` gains a `boolean hardTarget` field, true only for `night_compliance` (target 100 — a compliance floor). A hard target breaches on any shortfall; every other target uses the delta bands. This adds a field to the §5.1 record.

3. **One finding carries one tier but several references.** §6.2 stores `List<Reference> refs` ("every reference evaluated") alongside a single `tier`, `cause` and `gap`. **Resolution:** evaluate every declared reference, keep them all on the finding, take the **worst** tier. `cause` and `gap` come from the reference that produced that worst tier; ties break by the order the references are declared in.

4. **On-time and SLA-breach have no defined threshold.** §5.2 names the metrics but not what "on time" means. **Resolution:** on time is `actual_at <= scheduled_at + 5 min`; an SLA breach is `actual_at > scheduled_at + 15 min`. Both are named constants in `MetricConstants` so the real dataset can move them in one edit.

5. **A trip with a missing `actual_at` is excluded from both numerator and denominator**, not scored as late. Guessing "late" invents a fact; guessing "on time" hides one. The exclusion is counted as `nullCriticalFields`, so it lowers confidence and the narrative says so. This is what §3.2's "null-safe metric arithmetic" fault exists to prove.

6. **`night_compliance` needs a column the indicative schema does not have.** §3.1's `trips` columns carry no escort or marshal field. **Resolution:** the generator emits `night_escort BOOLEAN` on `trips`. Ingest is `union_by_name`, so a real dataset lacking the column yields all-NULL, which the gap register counts as `nullCriticalFields` — driving confidence below 0.5 and capping the rule at `WATCH`. The metric degrades instead of lying.

7. **`experience` would not need translation if it were `AVG(rating)`.** §5.2 makes metric 6 depend on the translation path, so the score must read the comment. **Resolution:** translation normalises `comment → comment_en` (a language task), then a **deterministic Java lexicon** assigns each response a sentiment in `{-1, 0, +1}`, and the per-response score is `clamp(rating + 0.5 * sentiment, 1, 5)`. The model does language; the arithmetic is unit-tested Java, so §1.1 holds. Responses whose comment could not be translated contribute sentiment `0` and count toward `nullCriticalFields`.

8. **Timezone.** Epoch milliseconds are absolute; "night trip" is local. All hour-of-day extraction shifts by IST: `epoch_ms(scheduled_at + 19800000)`. The constant lives in `MetricConstants.IST_OFFSET_MS`.

---

## The hour-seven checkpoint — how this plan enforces it

The proposal protects one thing above all: **a working agentic demo at ~7 hours elapsed**, so that running out of time leaves a complete narrow product rather than four unfinished halves.

The proposal's own checkpoint text is slightly at odds with its build order: item 5 sits after items 1–4 (dataset, ingest, registry, verdict) yet describes "one composed brief, one real Slack message", which is item 6. **This plan resolves it by putting a thin delivery slice inside Phase 1**: the pre-checkpoint brief is composed from a **deterministic template** and sent to the **real Slack webhook**. The Sarvam narrative, the numeric validator and email land in Phase 2 and *broaden* a loop that already runs end to end.

- **Phase 1 (Tasks 1–11)** is the protected slice. Not negotiable, not reorderable.
- **The gate between phases is a checklist, not a clock.** If hour seven arrives mid-task, finish that task and run the gate. If the gate fails, keep going on Phase 1 — Phase 2 does not start.
- **Phase 2 (Tasks 12–24) is still ordered by descending priority**, so a forced stop lands in the least damaging place. But nothing in it is planned as a cut — see the scope decision below.
- **Task 24 is reserved, not optional.** Deck, README, architecture diagram, and one offline rehearsal are scored deliverables. Start Task 24 no later than **1 h 30 before the deadline**, whatever is unfinished. Interrupt Phase 2 to do it.

### Scope decision: full scope, extended time — taken 2026-09-04, before Task 1

The estimates overrun the original timebox:

| | |
|---|---|
| Phase 1 (Tasks 1–11) | ~7 h 10 |
| Phase 2 (Tasks 12–23), of which | ~10 h 15 |
| — the two deployment tasks (16, 19) | ~1 h 30 |
| Task 24 (reserved) | ~1 h 30 |
| **Total** | **~18 h 55** |
| **Original timebox** | **~14 h** |

**The decision is to extend the time rather than strip scope.** All 24 tasks are
in. All six metrics ship. The vernacular pipeline ships. The interrogation panel
ships. Both deploys ship. Nothing on the proposal's droppable list is being
dropped.

This is a deliberate reversal of `PROPOSAL.md` §5's cut order, and it changes what
the plan optimises for. Three consequences follow, and they are the reason this
section exists rather than the decision being silent:

1. **The hour-seven checkpoint still stands, unchanged.** It is no longer a hedge
   against running out of time — it is now a *correctness* gate. Everything in
   Phase 2 is built on Phase 1's findings being right, so a red gate is a reason
   to stop and fix, not a reason to start cutting. Do not wave it through on the
   grounds that there is more time available.
2. **Task 24's 1 h 30 stays reserved and still starts 1 h 30 before whatever the
   deadline turns out to be.** Extending the build does not extend the deck. The
   deck, the diagram and the offline rehearsal are scored, and the rehearsal in
   particular is the highest-value 20 minutes in Phase 2.
3. **The priority order in Phase 2 is retained as a safety net, not a plan.** If
   the extension proves shorter than hoped, stopping after Task 18 still leaves a
   coherent product. Do not reorder Phase 2 to front-load the interesting tasks —
   that trades the safety net for nothing.

The estimates above are deliberately not padded. Track elapsed time against them
per task: if Phase 1 lands materially over 7 h 10, that is the signal to re-open
this decision, because it means the whole 18 h 55 figure is optimistic rather than
the box being too small.

**Deployment was added after the first draft**, at the human partner's request, as
Tasks 16 and 19 rather than as a step inside the deck task. Spec §11 names the
venues and criterion 3 (20%) asks for "deployable into an existing platform", so
this is scored work, not infrastructure hygiene. Both tasks sit early — the
service deploys as soon as its API is complete, the console as soon as it exists —
because a deploy first attempted near the deadline fails near the deadline, and
because deploying the console is what surfaces the fact that the Vite dev proxy
does not exist in production.

---

## File Structure

Two build roots in one repo. The service is Maven; the console is Vite. They share nothing but the HTTP contract, which is what makes the console droppable.

```
service/                                     Maven module, Java 21
  pom.xml
  src/main/resources/application.yaml
  src/main/java/com/signaldesk/
    SignalDeskApplication.java                Spring Boot entry point
    ingest/
      Feed.java                               enum: TRIPS, GPS_PINGS, DELAYS, COSTS, FEEDBACK, ROSTER
      TripLogSource.java                      interface { String globFor(Feed) } — local path or s3://
      LocalTripLogSource.java                 reads data/fixture/
      DuckDbLoader.java                       one tolerant view per feed; reads rejects back
      RejectRecord.java                       line, column, error, raw
      FeedHealth.java                         rowsLoaded/Rejected/unmatched/nullCritical/confidence
      GapRegister.java                        the coverage pass; one FeedHealth per feed
      FeedbackNormaliser.java                 comment -> comment_en -> sentiment; writes a table
      SentimentLexicon.java                   deterministic {-1,0,+1}; no model
    registry/
      Metric.java  Direction.java  ReferenceKind.java
      Dimension.java  Slice.java  Window.java
      MetricRegistry.java                     the six definitions; the only holder of SQL
      MetricRepository.java                   interface — the adapter seam for Athena/Aurora
      DuckDbMetricRepository.java             binds slice + window, returns one Double
      ReferenceResolver.java                  TREND, TARGET, PEER
      MetricConstants.java                    grace/breach/IST constants in one place
    verdict/
      Tier.java  Cause.java  Audience.java  Reference.java  Finding.java
      DeltaRule.java                          the delta formula and the four bands
      VerdictEngine.java                      all refs -> worst tier -> Finding
      Ranker.java                             (tier desc, |gap| desc, confidence desc)
      AudienceAssigner.java                   §6.4, returns a Set
      FindingId.java                          stable hash of metric+slice+window
    agent/
      Sweep.java                              the sense step: every metric x slice
      SweepScheduler.java                     @Scheduled; no prompt involved
      FindingStore.java                       in-memory, keyed by runId
      SweepRun.java                           runId, window, findings, feedHealth
      Composer.java                           interface: findings -> brief text
      TemplateComposer.java                   deterministic; the fallback and the Phase 1 brief
      SarvamComposer.java                     the model path, validated
      NarrativeValidator.java                 every figure must exist in the findings
      Dispatcher.java                         routes by tier; records what was sent
      DispatchLog.java
    delivery/
      Channel.java  SlackChannel.java  EmailChannel.java  DispatchResult.java
    model/
      ModelClient.java                        interface — keeps the model layer swappable
      SarvamClient.java                       OpenAI Java SDK + base-URL override
      Translator.java                         Sarvam translation; failure degrades, never blocks
      tools/
        Tool.java  ToolRegistry.java  ToolCallTrace.java
        ListMetricsTool.java  GetMetricTool.java
        ListFindingsTool.java  ExplainFindingTool.java
      Interrogator.java                       question -> tool calls -> answer + trace
    api/
      SweepController.java  FindingsController.java  FeedHealthController.java
      AskController.java  DispatchController.java
      dto/                                    wire shapes, kept separate from domain records
    fixture/
      FixtureGenerator.java                   main(); seeded; writes data/fixture/*.csv
      FaultInjector.java                      the seven planted faults
  src/test/java/com/signaldesk/…              mirrors the above
console/
  package.json  vite.config.ts  tsconfig.json  index.html
  src/main.tsx  src/App.tsx  src/api/client.ts  src/api/types.ts
  src/components/FindingsList.tsx  FindingRow.tsx  EvidencePanel.tsx
                 FeedHealthStrip.tsx  BriefPreview.tsx  InterrogationPanel.tsx
                 ToolTrace.tsx  TierBadge.tsx  Sparkline.tsx
  src/components/__tests__/…
data/fixture/*.csv                            committed; seed 20260904
Dockerfile                                   repo root: the build context needs service/ AND data/
.dockerignore
render.yaml                                  Render blueprint: BOTH services; every secret sync: false
console/.env.production.example              documents VITE_API_BASE; never the real value
```

**Why these boundaries:** `registry/` is the only package holding SQL, which is what makes the §1.1 invariant checkable by grep rather than by review. `verdict/` has no I/O and no clock, so it is pure-unit-testable — the property the whole trustworthiness argument rests on. `model/` sits behind `ModelClient` so Sarvam can be swapped without touching anything that computes. `MetricRepository` is the adapter seam the proposal promises a judge, so it must exist from Task 5, not be retrofitted.

---

# PHASE 1 — The protected vertical slice (Tasks 1–11, ~7 h 10)

Nothing in this phase is optional and nothing may be reordered. At the end of it
the agent senses on a clock tick, reasons without a model, composes a brief, and
posts it to a real Slack channel.

---

### Task 1: Service scaffold and a toolchain guard that fails the build (~0 h 30)

**Files:**
- Create: `service/pom.xml`
- Create: `service/src/main/java/com/signaldesk/SignalDeskApplication.java`
- Create: `service/src/main/resources/application.yaml`
- Create: `scripts/mvn.sh`
- Test: `service/src/test/java/com/signaldesk/ToolchainTest.java`
- Test: `service/src/test/java/com/signaldesk/SignalDeskApplicationTest.java`

**Interfaces:**
- Consumes: nothing.
- Produces: a bootable Spring Boot app; `scripts/mvn.sh` as the only sanctioned
  way to invoke Maven in this repo. Every later task's `Run:` lines use it.

The `JAVA_HOME` requirement is the single most likely way this build loses an
hour to a cryptic error, so it becomes an executable guard rather than a note in
a README.

- [ ] **Step 1: Write the failing toolchain test**

`service/src/test/java/com/signaldesk/ToolchainTest.java`:

```java
package com.signaldesk;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ToolchainTest {

    @Test
    void runsOnJdk21() {
        assertThat(Runtime.version().feature())
                .as("Homebrew Maven pulls JDK 26 and prefers it; Lombok and Spring "
                        + "plugins break on it. export JAVA_HOME=/opt/homebrew/opt/openjdk@21")
                .isEqualTo(21);
    }
}
```

- [ ] **Step 2: Run it and watch it fail for the right reason**

Run: `cd service && mvn -q test -Dtest=ToolchainTest`
Expected: FAIL — there is no `pom.xml` yet, so Maven reports
`The goal you specified requires a project to execute but there is no POM in this directory`.

- [ ] **Step 3: Write the POM**

`service/pom.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.5.5</version>
    <relativePath/>
  </parent>

  <groupId>com.signaldesk</groupId>
  <artifactId>signal-desk-service</artifactId>
  <version>0.1.0</version>
  <name>Signal Desk Service</name>

  <properties>
    <java.version>21</java.version>
    <maven.compiler.release>21</maven.compiler.release>
    <duckdb.version>1.5.5</duckdb.version>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.duckdb</groupId>
      <artifactId>duckdb_jdbc</artifactId>
      <version>${duckdb.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-enforcer-plugin</artifactId>
        <executions>
          <execution>
            <id>enforce-jdk-21</id>
            <goals><goal>enforce</goal></goals>
            <configuration>
              <rules>
                <requireJavaVersion><version>[21,22)</version></requireJavaVersion>
              </rules>
            </configuration>
          </execution>
        </executions>
      </plugin>
    </plugins>
  </build>
</project>
```

The enforcer rule is deliberate belt-and-braces: it fails `mvn compile` on a
wrong JDK, before any test runs, with a message that names the version.

- [ ] **Step 4: Verify the DuckDB coordinate actually resolves**

Run: `cd service && mvn -q dependency:get -Dartifact=org.duckdb:duckdb_jdbc:1.5.5`
Expected: PASS.

If it fails, `AGENTS.md`'s claim that the installed CLI 1.5.5 matches an
available JDBC driver is wrong. Do not guess a nearby version: run
`mvn dependency:list-repositories` then resolve the newest published
`org.duckdb:duckdb_jdbc`, set `<duckdb.version>` to it, and **check that
`duckdb --version` on the CLI matches** — a fixture written by one version and
read by another is a debugging session nobody has time for. Record whichever
version you land on in the commit message.

- [ ] **Step 5: Write the application class and config**

`service/src/main/java/com/signaldesk/SignalDeskApplication.java`:

```java
package com.signaldesk;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class SignalDeskApplication {
    public static void main(String[] args) {
        SpringApplication.run(SignalDeskApplication.class, args);
    }
}
```

`service/src/main/resources/application.yaml`:

```yaml
server:
  port: 8080
signaldesk:
  fixture-dir: ../data/fixture
  sweep:
    cron: "0 */15 * * * *"      # the sense step: fires with no prompt
    enabled: true
  window-days: 7
spring:
  main:
    banner-mode: off
logging:
  level:
    com.signaldesk: INFO
```

- [ ] **Step 6: Write the context-load test**

`service/src/test/java/com/signaldesk/SignalDeskApplicationTest.java`:

```java
package com.signaldesk;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class SignalDeskApplicationTest {

    @Test
    void contextLoads() {
        // asserts by not throwing: a broken bean graph fails here, not at hour ten
    }
}
```

- [ ] **Step 7: Write the Maven wrapper script**

`scripts/mvn.sh`:

```sh
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
```

- [ ] **Step 8: Run both tests through the script**

Run: `chmod +x scripts/mvn.sh && ./scripts/mvn.sh -q test`
Expected: PASS, 2 tests.

- [ ] **Step 9: Prove the guard is not vacuous**

Run: `JAVA_HOME=$(/usr/libexec/java_home -v 22 2>/dev/null || echo "") mvn -f service/pom.xml -q test -Dtest=ToolchainTest`
Expected: FAIL on the enforcer rule or the assertion, naming the version found.

If no JDK other than 21 is installed, temporarily change the assertion to
`isEqualTo(17)`, confirm it fails, and change it back. A toolchain guard that
cannot fail is not a guard.

- [ ] **Step 10: Commit**

```bash
git add service scripts/mvn.sh
git commit -m "feat(service): Spring Boot scaffold with an executable JDK 21 guard"
```

---

### Task 2: Deterministic fixture generator with seven planted faults (~1 h 15)

**Files:**
- Create: `service/src/main/java/com/signaldesk/ingest/Feed.java`
- Create: `service/src/main/java/com/signaldesk/fixture/FixtureGenerator.java`
- Create: `service/src/main/java/com/signaldesk/fixture/FaultInjector.java`
- Create: `data/fixture/*.csv` (generated output, committed)
- Test: `service/src/test/java/com/signaldesk/fixture/FixtureGeneratorTest.java`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `enum Feed { TRIPS, GPS_PINGS, DELAYS, COSTS, FEEDBACK, ROSTER }` with
    `String fileName()` returning `"trips.csv"` etc.
  - `FixtureGenerator.generate(Path outDir, long seed)` — writes one CSV per feed
  - `FixtureGenerator.SEED = 20260904L`, `DEGRADING_VENDOR = "V07"`,
    `FixtureGenerator.DAYS = 90`, `windowEnd()` returning the epoch-ms end of the
    last complete day. Tasks 5, 6, 9 and 10 all read these.

**Two notes before starting.**

*Malformed rows are emitted as an extra trailing field, not as a wrong type.*
The spec asks for "bad delimiters, wrong types". A wrong type is unreliable as a
fault: `read_csv_auto` sniffs a column's type from a sample, and one `"n/a"` in
a numeric column makes the whole column `VARCHAR`, at which point nothing is
rejected and the test asserts nothing. A row with one field too many is rejected
regardless of sniffing. This is a deliberate narrowing of §3.2's wording to keep
the test honest.

*Feedback comments come from a fixed phrase table.* Real translation is not
deterministic, so the generator must not depend on it. Task 21's normalised
feedback is materialised into a table once and cached; the sweep determinism test
runs against a stub translator.

- [ ] **Step 1: Write the failing determinism test**

`service/src/test/java/com/signaldesk/fixture/FixtureGeneratorTest.java`:

```java
package com.signaldesk.fixture;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.ingest.Feed;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class FixtureGeneratorTest {

    @Test
    void sameSeedProducesByteIdenticalOutputForEveryFeed(@TempDir Path a, @TempDir Path b) throws Exception {
        FixtureGenerator.generate(a, FixtureGenerator.SEED);
        FixtureGenerator.generate(b, FixtureGenerator.SEED);

        for (Feed feed : Feed.values()) {
            assertThat(Files.readAllBytes(a.resolve(feed.fileName())))
                    .as("feed %s must be byte-identical across runs", feed)
                    .isEqualTo(Files.readAllBytes(b.resolve(feed.fileName())));
        }
    }

    @Test
    void differentSeedsProduceDifferentTrips(@TempDir Path a, @TempDir Path b) throws Exception {
        FixtureGenerator.generate(a, FixtureGenerator.SEED);
        FixtureGenerator.generate(b, FixtureGenerator.SEED + 1);

        assertThat(Files.readAllBytes(a.resolve(Feed.TRIPS.fileName())))
                .isNotEqualTo(Files.readAllBytes(b.resolve(Feed.TRIPS.fileName())));
    }
}
```

The second test is what stops the first from passing under a generator that
writes constants. Six feeds compared plus a negative case is the "two or more
data points" rule applied to a determinism claim.

- [ ] **Step 2: Run it to verify it fails**

Run: `./scripts/mvn.sh -q test -Dtest=FixtureGeneratorTest`
Expected: FAIL — `cannot find symbol: class FixtureGenerator`.

- [ ] **Step 3: Write the Feed enum**

`service/src/main/java/com/signaldesk/ingest/Feed.java`:

```java
package com.signaldesk.ingest;

public enum Feed {
    TRIPS("trips"),
    GPS_PINGS("gps_pings"),
    DELAYS("delays"),
    COSTS("costs"),
    FEEDBACK("feedback"),
    ROSTER("roster");

    private final String base;

    Feed(String base) {
        this.base = base;
    }

    /** The DuckDB view name, which is also the CSV stem. */
    public String viewName() {
        return base;
    }

    public String fileName() {
        return base + ".csv";
    }
}
```

- [ ] **Step 4: Write the generator**

`service/src/main/java/com/signaldesk/fixture/FixtureGenerator.java`:

```java
package com.signaldesk.fixture;

import com.signaldesk.ingest.Feed;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Random;

/**
 * Writes the committed demo fixture. Seeded, so the same seed produces
 * byte-identical output: no Math.random, no wall-clock reads.
 *
 * java.util.Random is used rather than SplittableRandom because its algorithm is
 * contractually specified, so output is identical across JVM implementations.
 */
public final class FixtureGenerator {

    public static final long SEED = 20260904L;
    public static final int DAYS = 90;
    public static final int TRIP_COUNT = 8_000;
    public static final int VENDOR_COUNT = 12;
    public static final int SITE_COUNT = 4;
    public static final String DEGRADING_VENDOR = "V07";
    /** The vendor regression covers the final three weeks — the demo narrative. */
    public static final int REGRESSION_DAYS = 21;

    static final String[] SHIFTS = {"S1", "S2", "S3"};
    static final String[] MODES = {"cab", "nodal", "shuttle"};
    static final String[] DIRECTIONS = {"login", "logout"};
    static final LocalDate DAY_ZERO = LocalDate.parse("2026-06-07");

    private FixtureGenerator() {}

    public static long dayStartMs(int day) {
        return DAY_ZERO.plusDays(day).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli();
    }

    /** Exclusive end of the last complete day; the sweep windows back from here. */
    public static long windowEnd() {
        return dayStartMs(DAYS);
    }

    /**
     * All six writers share ONE Random. Inserting or removing a single draw
     * anywhere shifts every subsequent value and changes the committed fixture
     * byte-for-byte. theCommittedFixtureMatchesWhatTheGeneratorProducesNow will
     * catch it, but know it before you edit rather than after.
     */
    public static void generate(Path outDir, long seed) throws IOException {
        Files.createDirectories(outDir);
        Random rnd = new Random(seed);

        List<Trip> trips = buildTrips(rnd);
        writeTrips(outDir, trips, rnd);
        writeGpsPings(outDir, trips, rnd);
        writeDelays(outDir, trips, rnd);
        writeCosts(outDir, trips, rnd);
        writeFeedback(outDir, trips, rnd);
        writeRoster(outDir, trips, rnd);
    }

    record Trip(String tripId, int day, String shift, String mode, String siteId,
                String vendorId, String driverId, String vehicleId, String direction,
                long scheduledAt, Long actualAt, double plannedKm, double actualKm,
                int seats, int occupancy, String status, boolean nightEscort) {}

    private static List<Trip> buildTrips(Random rnd) {
        List<Trip> out = new ArrayList<>(TRIP_COUNT);
        for (int i = 0; i < TRIP_COUNT; i++) {
            int day = rnd.nextInt(DAYS);
            String shift = SHIFTS[rnd.nextInt(SHIFTS.length)];
            String direction = DIRECTIONS[rnd.nextInt(DIRECTIONS.length)];
            String vendorId = String.format("V%02d", rnd.nextInt(VENDOR_COUNT) + 1);
            String siteId = String.format("SITE%d", rnd.nextInt(SITE_COUNT) + 1);

            long scheduledAt = dayStartMs(day) + shiftOffsetMs(shift, direction);
            double p = onTimeProbability(vendorId, shift, day);
            boolean onTime = rnd.nextDouble() < p;
            long latenessMin = onTime ? rnd.nextInt(5) : 6 + rnd.nextInt(40);

            // Planted fault: ~2% of trips never close out.
            Long actualAt = rnd.nextDouble() < 0.02 ? null : scheduledAt + latenessMin * 60_000L;

            double plannedKm = 8 + rnd.nextInt(35) + rnd.nextDouble();
            double actualKm = plannedKm * (0.95 + rnd.nextDouble() * 0.2);
            String mode = MODES[rnd.nextInt(MODES.length)];
            int seats = switch (mode) { case "cab" -> 4; case "nodal" -> 12; default -> 24; };
            int occupancy = 1 + rnd.nextInt(seats);

            // Night-trip escort compliance: mostly honoured, and the degrading
            // vendor is worse at it too, so two metrics point at one vendor.
            boolean night = isNightTrip(shift, direction);
            double escortP = DEGRADING_VENDOR.equals(vendorId) ? 0.72 : 0.97;
            boolean nightEscort = !night || rnd.nextDouble() < escortP;

            out.add(new Trip(String.format("T%06d", i), day, shift, mode, siteId, vendorId,
                    String.format("D%04d", rnd.nextInt(400)),
                    String.format("KA01AB%04d", rnd.nextInt(2000)),
                    direction, scheduledAt, actualAt, plannedKm, actualKm, seats, occupancy,
                    actualAt == null ? "open" : "closed", nightEscort));
        }
        return out;
    }

    /** Deterministic per-vendor baseline plus the planted three-week regression. */
    static double onTimeProbability(String vendorId, String shift, int day) {
        double p = 0.91 - 0.005 * (Integer.parseInt(vendorId.substring(1)) % 13);
        if ("S3".equals(shift)) {
            p -= 0.05;
        }
        if (DEGRADING_VENDOR.equals(vendorId)) {
            int intoRegression = day - (DAYS - REGRESSION_DAYS) + 1;
            if (intoRegression > 0) {
                p -= 0.30 * intoRegression / (double) REGRESSION_DAYS;
            }
        }
        return p;
    }

    /**
     * The SAME rule the night_compliance SQL uses: a logout trip whose local IST
     * hour is 22:00–05:59. Derived here rather than hardcoded to a shift, because
     * an earlier draft hardcoded "S3 logout" while the SQL tested the IST hour —
     * S3 logout landed at 06:00 IST, the predicate excluded it, and the metric
     * silently matched zero rows. One rule, one place.
     */
    static boolean isNightTrip(String shift, String direction) {
        if (!"logout".equals(direction)) {
            return false;
        }
        long istHour = istHourFor(shift, direction);
        return istHour >= MetricNight.START_HOUR || istHour < MetricNight.END_HOUR;
    }

    /** Local IST hour a shift's trip is scheduled for. */
    static long istHourFor(String shift, String direction) {
        return switch (shift) {
            case "S1" -> "login".equals(direction) ? 8 : 17;
            case "S2" -> "login".equals(direction) ? 14 : 23;   // 23:00 IST — a night logout
            default -> "login".equals(direction) ? 21 : 5;      // 05:00 IST — a night logout
        };
    }

    /** The scheduled offset from UTC day start for that IST hour. */
    static long shiftOffsetMs(String shift, String direction) {
        return istHourFor(shift, direction) * 3_600_000L - IST_OFFSET_MS;
    }

    /**
     * Duplicated from MetricConstants deliberately: the fixture package must not
     * depend on the registry package, and these two values agreeing is asserted by
     * a test rather than assumed. Change both together.
     */
    static final class MetricNight {
        static final int START_HOUR = 22;
        static final int END_HOUR = 6;
    }

    static final long IST_OFFSET_MS = 19_800_000L;

    private static void writeTrips(Path dir, List<Trip> trips, Random rnd) throws IOException {
        try (BufferedWriter w = writer(dir, Feed.TRIPS)) {
            w.write("trip_id,date,shift,mode,site_id,vendor_id,driver_id,vehicle_id,"
                    + "direction,scheduled_at,actual_at,planned_km,actual_km,seats,"
                    + "occupancy,status,night_escort\n");
            for (Trip t : trips) {
                String row = String.join(",",
                        t.tripId(), Long.toString(dayStartMs(t.day())), t.shift(), t.mode(),
                        t.siteId(), t.vendorId(), t.driverId(), t.vehicleId(), t.direction(),
                        Long.toString(t.scheduledAt()),
                        t.actualAt() == null ? "" : Long.toString(t.actualAt()),
                        fmt(t.plannedKm()), fmt(t.actualKm()),
                        Integer.toString(t.seats()), Integer.toString(t.occupancy()),
                        t.status(), Boolean.toString(t.nightEscort()));
                w.write(FaultInjector.maybeMalform(row, rnd));
                w.write('\n');
            }
        }
    }

    private static void writeGpsPings(Path dir, List<Trip> trips, Random rnd) throws IOException {
        try (BufferedWriter w = writer(dir, Feed.GPS_PINGS)) {
            w.write("trip_id,ts,lat,lng\n");
            for (Trip t : trips) {
                boolean gapped = rnd.nextDouble() < 0.12;    // planted fault: ~12% of traces
                int pings = 20;
                for (int i = 0; i < pings; i++) {
                    if (gapped && i >= 7 && i < 14) {
                        continue;                            // a hole mid-trip, not a short trace
                    }
                    long ts = t.scheduledAt() + i * 120_000L;
                    double lat = 12.90 + 0.02 * i / pings + 0.0001 * rnd.nextInt(50);
                    double lng = 77.55 + 0.02 * i / pings + 0.0001 * rnd.nextInt(50);
                    w.write(String.join(",", t.tripId(), Long.toString(ts), fmt6(lat), fmt6(lng)));
                    w.write('\n');
                }
            }
        }
    }

    private static void writeDelays(Path dir, List<Trip> trips, Random rnd) throws IOException {
        String[] reasons = {"TRAFFIC", "VEHICLE_BREAKDOWN", "DRIVER_LATE", "WEATHER", "GATE_HOLD"};
        try (BufferedWriter w = writer(dir, Feed.DELAYS)) {
            w.write("trip_id,reason_code,minutes,recorded_at\n");
            for (Trip t : trips) {
                if (t.actualAt() == null) {
                    continue;
                }
                long lateMin = (t.actualAt() - t.scheduledAt()) / 60_000L;
                if (lateMin < 6) {
                    continue;
                }
                w.write(String.join(",", t.tripId(), reasons[rnd.nextInt(reasons.length)],
                        Long.toString(lateMin), Long.toString(t.actualAt())));
                w.write('\n');
            }
        }
    }

    private static void writeCosts(Path dir, List<Trip> trips, Random rnd) throws IOException {
        try (BufferedWriter w = writer(dir, Feed.COSTS)) {
            w.write("trip_id,vendor_id,base_inr,km_inr,wait_inr,total_inr\n");
            for (Trip t : trips) {
                // The degrading vendor also bills more waiting time, so cost_per_trip
                // and vendor_ota corroborate each other in the brief.
                int waitInr = DEGRADING_VENDOR.equals(t.vendorId())
                        ? 40 + rnd.nextInt(160) : 10 + rnd.nextInt(60);
                int baseInr = 120 + rnd.nextInt(80);
                int kmInr = (int) Math.round(t.actualKm() * 14);
                String tripId = FaultInjector.maybeUnmatch(t.tripId(), rnd);
                w.write(String.join(",", tripId, t.vendorId(), Integer.toString(baseInr),
                        Integer.toString(kmInr), Integer.toString(waitInr),
                        Integer.toString(baseInr + kmInr + waitInr)));
                w.write('\n');
            }
        }
    }

    private static void writeFeedback(Path dir, List<Trip> trips, Random rnd) throws IOException {
        try (BufferedWriter w = writer(dir, Feed.FEEDBACK)) {
            w.write("trip_id,employee_id,rating,comment,language\n");
            for (Trip t : trips) {
                if (rnd.nextDouble() > 0.35) {
                    continue;                                // not every trip is rated
                }
                boolean late = t.actualAt() != null && t.actualAt() - t.scheduledAt() > 900_000L;
                int rating = late ? 1 + rnd.nextInt(3) : 3 + rnd.nextInt(3);
                FaultInjector.Comment c = FaultInjector.comment(rating, rnd);
                String tripId = FaultInjector.maybeUnmatch(t.tripId(), rnd);
                w.write(String.join(",", tripId, String.format("E%05d", rnd.nextInt(4000)),
                        Integer.toString(rating), quote(c.text()), c.language()));
                w.write('\n');
            }
        }
    }

    private static void writeRoster(Path dir, List<Trip> trips, Random rnd) throws IOException {
        try (BufferedWriter w = writer(dir, Feed.ROSTER)) {
            w.write("employee_id,site_id,shift,date,expected\n");
            for (int day = 0; day < DAYS; day++) {
                for (int i = 0; i < 40; i++) {
                    // Planted fault: ~5% of roster rows name employees with no trip.
                    boolean orphan = rnd.nextDouble() < FaultInjector.ORPHAN_ROSTER_RATE;
                    String employeeId = orphan
                            ? String.format("E9%04d", rnd.nextInt(1000))
                            : String.format("E%05d", rnd.nextInt(4000));
                    w.write(String.join(",", employeeId,
                            String.format("SITE%d", rnd.nextInt(SITE_COUNT) + 1),
                            SHIFTS[rnd.nextInt(SHIFTS.length)],
                            Long.toString(dayStartMs(day)), "1"));
                    w.write('\n');
                }
            }
        }
    }

    private static BufferedWriter writer(Path dir, Feed feed) throws IOException {
        return Files.newBufferedWriter(dir.resolve(feed.fileName()), StandardCharsets.UTF_8);
    }

    // Locale.ROOT is not optional. String.format without it uses the JVM's
    // default locale, and a comma decimal separator would write "12,34" into a
    // CSV field — breaking field counting (indistinguishable from the planted
    // malformed-row fault) and breaking byte-identical output across machines.
    private static String fmt(double d) {
        return String.format(Locale.ROOT, "%.2f", d);
    }

    private static String fmt6(double d) {
        return String.format(Locale.ROOT, "%.6f", d);
    }

    private static String quote(String s) {
        return '"' + s.replace("\"", "\"\"") + '"';
    }

    public static void main(String[] args) throws IOException {
        Path out = Path.of(args.length > 0 ? args[0] : "../data/fixture");
        generate(out, SEED);
        // Print the ABSOLUTE path: exec:java inherits the shell's cwd rather than
        // ${basedir}, so the default relative argument can land outside the repo.
        // Reading this line is how that gets caught.
        System.out.println("fixture written to " + out.toAbsolutePath().normalize()
                + " (seed " + SEED + ")");
    }
}
```

- [ ] **Step 5: Write the fault injector**

`service/src/main/java/com/signaldesk/fixture/FaultInjector.java`:

```java
package com.signaldesk.fixture;

import java.util.Random;

/**
 * The seven planted faults from spec §3.2. They are required, not incidental:
 * "handles messy or missing data gracefully" cannot be demonstrated on clean data.
 */
public final class FaultInjector {

    /** ~1.5% of rows. An extra trailing field, which DuckDB rejects regardless of type sniffing. */
    public static final double MALFORMED_RATE = 0.015;
    /** ~3% of costs/feedback rows point at a trip_id that does not exist. */
    public static final double UNMATCHED_RATE = 0.03;
    /** ~40% of feedback comments are not in English. */
    public static final double NON_ENGLISH_RATE = 0.40;
    /** ~5% of roster rows name an employee who never took a trip. */
    public static final double ORPHAN_ROSTER_RATE = 0.05;

    private FaultInjector() {}

    public static String maybeMalform(String row, Random rnd) {
        return rnd.nextDouble() < MALFORMED_RATE ? row + ",UNEXPECTED_EXTRA_FIELD" : row;
    }

    public static String maybeUnmatch(String tripId, Random rnd) {
        return rnd.nextDouble() < UNMATCHED_RATE
                ? String.format("T99%04d", rnd.nextInt(10_000))
                : tripId;
    }

    public record Comment(String text, String language) {}

    private static final String[][] POSITIVE = {
        {"Driver was punctual and polite", "en"},
        {"Cab samay par aaya, driver acha tha", "hi"},
        {"Vandi sariyana neratthil vanthathu", "ta"},
        {"Cab samayakke bantu, chennagitru", "kn"},
        {"Driver samayaniki vachadu, baagundi", "te"},
    };

    private static final String[][] NEGATIVE = {
        {"Waited forty minutes with no update", "en"},
        {"Cab bahut late tha, koi soochna nahi mili", "hi"},
        {"Vandi romba late, thagaval illai", "ta"},
        {"Cab tumba late aytu, maahiti sigalilla", "kn"},
        {"Cab chala late ayindi, sammachaaram ledu", "te"},
    };

    /**
     * Comments come from a fixed table because real translation is not
     * deterministic and the generator must be. Rating drives polarity so the
     * lexicon in Task 21 has a real signal to find.
     */
    public static Comment comment(int rating, Random rnd) {
        String[][] pool = rating <= 2 ? NEGATIVE : POSITIVE;
        int idx = rnd.nextDouble() < NON_ENGLISH_RATE ? 1 + rnd.nextInt(pool.length - 1) : 0;
        return new Comment(pool[idx][0], pool[idx][1]);
    }
}
```

- [ ] **Step 6: Run the determinism tests**

Run: `./scripts/mvn.sh -q test -Dtest=FixtureGeneratorTest`
Expected: PASS, 2 tests.

- [ ] **Step 7: Add the fault-rate tests**

Append to `FixtureGeneratorTest`:

```java
    @Test
    void plantsEveryRequiredFaultAtRoughlyTheSpecifiedRate(@TempDir Path dir) throws Exception {
        FixtureGenerator.generate(dir, FixtureGenerator.SEED);

        List<String> trips = Files.readAllLines(dir.resolve(Feed.TRIPS.fileName()));
        List<String> body = trips.subList(1, trips.size());
        int headerFields = trips.get(0).split(",", -1).length;

        long malformed = body.stream().filter(r -> r.split(",", -1).length != headerFields).count();
        assertThat(malformed / (double) body.size()).as("malformed rows").isBetween(0.008, 0.025);

        long missingActual = body.stream()
                .filter(r -> r.split(",", -1).length == headerFields)
                .filter(r -> r.split(",", -1)[10].isEmpty()).count();
        assertThat(missingActual / (double) body.size()).as("unclosed trips").isBetween(0.012, 0.030);

        List<String> costs = Files.readAllLines(dir.resolve(Feed.COSTS.fileName()));
        long unmatched = costs.stream().skip(1).filter(r -> r.startsWith("T99")).count();
        assertThat(unmatched / (double) (costs.size() - 1)).as("unmatched costs").isBetween(0.02, 0.045);

        List<String> feedback = Files.readAllLines(dir.resolve(Feed.FEEDBACK.fileName()));
        long nonEnglish = feedback.stream().skip(1).filter(r -> !r.endsWith(",en")).count();
        assertThat(nonEnglish / (double) (feedback.size() - 1)).as("non-English").isBetween(0.30, 0.50);

        long unmatchedFeedback = feedback.stream().skip(1).filter(r -> r.startsWith("T99")).count();
        assertThat(unmatchedFeedback / (double) (feedback.size() - 1))
                .as("unmatched feedback").isBetween(0.02, 0.045);

        List<String> roster = Files.readAllLines(dir.resolve(Feed.ROSTER.fileName()));
        long orphanRoster = roster.stream().skip(1).filter(r -> r.startsWith("E9")).count();
        assertThat(orphanRoster / (double) (roster.size() - 1))
                .as("orphan roster rows").isBetween(0.03, 0.07);

        List<String> pings = Files.readAllLines(dir.resolve(Feed.GPS_PINGS.fileName()));
        Map<String, Long> perTrip = pings.stream().skip(1)
                .collect(Collectors.groupingBy(r -> r.split(",")[0], Collectors.counting()));
        long gapped = perTrip.values().stream().filter(n -> n < 20).count();
        assertThat(gapped / (double) perTrip.size()).as("gapped GPS traces").isBetween(0.09, 0.16);
    }

    @Test
    void theDegradingVendorIsActuallyWorseInTheFinalThreeWeeks() {
        int lastDay = FixtureGenerator.DAYS - 1;
        int beforeRegression = FixtureGenerator.DAYS - FixtureGenerator.REGRESSION_DAYS - 5;

        double lateDegrading = FixtureGenerator.onTimeProbability(
                FixtureGenerator.DEGRADING_VENDOR, "S1", lastDay);
        double earlyDegrading = FixtureGenerator.onTimeProbability(
                FixtureGenerator.DEGRADING_VENDOR, "S1", beforeRegression);
        double latePeer = FixtureGenerator.onTimeProbability("V03", "S1", lastDay);

        assertThat(lateDegrading)
                .as("V07 must be materially worse than its own earlier self")
                .isLessThan(earlyDegrading - 0.20);
        assertThat(lateDegrading)
                .as("and worse than a peer in the same window")
                .isLessThan(latePeer - 0.20);
    }

    @Test
    void everyNightLogoutShiftIsClassifiedByTheIstHourRuleNotByShiftName() {
        // An earlier draft hardcoded "S3 logout is night" while the metric SQL
        // tested the IST hour. S3 logout sat at 06:00 IST, the predicate excluded
        // it, and the metric matched zero rows. These assertions pin the rule to
        // the hour. The cross-package agreement with MetricConstants is asserted
        // in Task 5, the first task where both sides exist.
        assertThat(FixtureGenerator.isNightTrip("S2", "logout"))
                .as("23:00 IST is a night logout").isTrue();
        assertThat(FixtureGenerator.isNightTrip("S3", "logout"))
                .as("05:00 IST is a night logout").isTrue();
        assertThat(FixtureGenerator.isNightTrip("S1", "logout"))
                .as("17:00 IST is not").isFalse();
        assertThat(FixtureGenerator.isNightTrip("S3", "login"))
                .as("a login is never a night trip, whatever the hour").isFalse();
    }
```

Add the imports `java.util.Map` and `java.util.stream.Collectors`. `SHIFTS`,
`istHourFor`, `isNightTrip`, `MetricNight` and `IST_OFFSET_MS` are
package-private on `FixtureGenerator`, and this test class is already in package
`com.signaldesk.fixture`, so no visibility change is needed.

The second test asserts two comparisons, not one: a regression that is only
visible against the vendor's own past would not drive the peer-comparison
narrative, and one that is only visible against peers would not drive the trend
narrative. The brief needs both.

- [ ] **Step 8: Run the fault tests**

Run: `./scripts/mvn.sh -q test -Dtest=FixtureGeneratorTest`
Expected: PASS, 5 tests.

- [ ] **Step 9: Break-it-to-prove-it**

Falsify each rate guard, one at a time, restoring between each:

- `FaultInjector.MALFORMED_RATE = 0.0` → the malformed assertion FAILS
- `FaultInjector.UNMATCHED_RATE = 0.0` → both the unmatched-costs and
  unmatched-feedback assertions FAIL
- `FaultInjector.ORPHAN_ROSTER_RATE = 0.0` → the orphan-roster assertion FAILS
- the `intoRegression > 0` branch made a no-op →
  `theDegradingVendorIsActuallyWorseInTheFinalThreeWeeks` FAILS
- `istHourFor`'s S3 logout changed back to `6` →
  `everyNightLogoutShiftIsClassifiedByTheIstHourRuleNotByShiftName` FAILS

The last one is the mismatch that made `night_compliance` match zero rows in an
earlier draft. Knowing empirically that the test fires is worth the minute.

Then prove the locale guard, if your shell makes it easy: run the determinism
tests with `-Duser.language=de -Duser.country=DE`. They pass with `Locale.ROOT`
and fail without it. Skip and say so if it turns fiddly — the code fix stands on
its own.

- [ ] **Step 10: Generate and commit the fixture**

**Pass the output directory explicitly.** Unlike Surefire, `exec:java` does *not*
default its working directory to `${basedir}` — it inherits the shell's cwd, which
is the repo root when you invoke `./scripts/mvn.sh`. `main()`'s default argument of
`../data/fixture` is written for a `service/`-relative cwd, so running this
command bare writes the fixture **one level above the repository**. That was
observed, not theorised.

Run, from the repo root:
```bash
./scripts/mvn.sh -q compile
./scripts/mvn.sh -q exec:java \
  -Dexec.mainClass=com.signaldesk.fixture.FixtureGenerator \
  -Dexec.args=data/fixture
wc -l data/fixture/*.csv
du -sh data/fixture
```
Expected: six files; `trips.csv` 8,001 lines; `gps_pings.csv` around 153,600
lines; the whole directory under 10 MB, small enough for git.

`main()` prints the absolute path it wrote to. **Read that line** rather than
assuming — if it names anything outside this repository, delete what it wrote and
re-run with the explicit `-Dexec.args`.

Add `exec-maven-plugin` to the POM's `<build><plugins>` (it is not there after
Task 1):

```xml
      <plugin>
        <groupId>org.codehaus.mojo</groupId>
        <artifactId>exec-maven-plugin</artifactId>
        <version>3.5.0</version>
      </plugin>
```

- [ ] **Step 11: Pin the committed fixture against regeneration**

Append to `FixtureGeneratorTest`:

```java
    @Test
    void theCommittedFixtureMatchesWhatTheGeneratorProducesNow(@TempDir Path fresh) throws Exception {
        Path committed = Path.of("..", "data", "fixture");
        assumeTrue(Files.isDirectory(committed), "committed fixture not present");

        FixtureGenerator.generate(fresh, FixtureGenerator.SEED);
        for (Feed feed : Feed.values()) {
            assertThat(Files.readAllBytes(fresh.resolve(feed.fileName())))
                    .as("committed %s has drifted from the generator — regenerate, do not hand-edit", feed)
                    .isEqualTo(Files.readAllBytes(committed.resolve(feed.fileName())));
        }
    }
```

Add `import static org.junit.jupiter.api.Assumptions.assumeTrue;`.

- [ ] **Step 12: Commit**

```bash
git add service data/fixture
git commit -m "feat(fixture): seeded generator with the seven planted faults, plus the committed fixture"
```

---

### Task 3: Tolerant DuckDB ingest with a rejects quarantine (~0 h 45)

**Files:**
- Create: `service/src/main/java/com/signaldesk/ingest/TripLogSource.java`
- Create: `service/src/main/java/com/signaldesk/ingest/LocalTripLogSource.java`
- Create: `service/src/main/java/com/signaldesk/ingest/RejectRecord.java`
- Create: `service/src/main/java/com/signaldesk/ingest/DuckDbLoader.java`
- Test: `service/src/test/java/com/signaldesk/ingest/DuckDbLoaderTest.java`

**Interfaces:**
- Consumes: `Feed` (Task 2), the committed fixture.
- Produces:
  - `interface TripLogSource { String globFor(Feed feed); }`
  - `DuckDbLoader(DataSource ds, TripLogSource source)` with
    `void loadAll()`, `long rowsLoaded(Feed)`, `List<RejectRecord> rejects(Feed)`
  - `record RejectRecord(Feed feed, long line, String column, String error, String raw)`
  - A `Connection` on an in-process DuckDB instance, exposed as a Spring
    `DataSource` bean so Tasks 4–6 can query it.

- [ ] **Step 1: Write the failing quarantine test**

`service/src/test/java/com/signaldesk/ingest/DuckDbLoaderTest.java`:

```java
package com.signaldesk.ingest;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DuckDbLoaderTest {

    private Connection conn;

    @BeforeEach
    void openInMemoryDuckDb() throws Exception {
        conn = DriverManager.getConnection("jdbc:duckdb:");
    }

    @AfterEach
    void close() throws Exception {
        conn.close();
    }

    @Test
    void aMalformedRowIsQuarantinedAndCountedRatherThanDropped(@TempDir Path dir) throws Exception {
        Files.writeString(dir.resolve("trips.csv"), """
                trip_id,vendor_id,scheduled_at
                T000001,V01,100
                T000002,V01,200,UNEXPECTED_EXTRA_FIELD
                T000003,V02,300
                """);

        DuckDbLoader loader = new DuckDbLoader(conn, feed -> dir.resolve(feed.fileName()).toString());
        loader.load(Feed.TRIPS);

        assertThat(loader.rowsLoaded(Feed.TRIPS)).as("the two good rows survive").isEqualTo(2);
        assertThat(loader.rejects(Feed.TRIPS))
                .as("the bad row is inspectable, not silently lost")
                .hasSize(1)
                .allSatisfy(r -> assertThat(r.line()).isEqualTo(3L));
    }

    @Test
    void unionByNameMergesTwoFilesWithDifferentColumnSets(@TempDir Path dir) throws Exception {
        Files.writeString(dir.resolve("trips_a.csv"), """
                trip_id,vendor_id
                T000001,V01
                """);
        Files.writeString(dir.resolve("trips_b.csv"), """
                trip_id,site_id
                T000002,SITE1
                """);

        DuckDbLoader loader = new DuckDbLoader(conn, feed -> dir.resolve("trips_*.csv").toString());
        loader.load(Feed.TRIPS);

        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery(
                     "SELECT count(*) AS n, count(vendor_id) AS v, count(site_id) AS t FROM trips")) {
            rs.next();
            assertThat(rs.getLong("n")).isEqualTo(2);
            assertThat(rs.getLong("v")).as("column present in only one file").isEqualTo(1);
            assertThat(rs.getLong("t")).as("and the other").isEqualTo(1);
        }
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./scripts/mvn.sh -q test -Dtest=DuckDbLoaderTest`
Expected: FAIL — `cannot find symbol: class DuckDbLoader`.

- [ ] **Step 3: Write the source interface and the reject record**

`service/src/main/java/com/signaldesk/ingest/TripLogSource.java`:

```java
package com.signaldesk.ingest;

/**
 * The whole engine's knowledge of where data lives. A local path on the day, an
 * s3:// glob in production — the query is identical either way, which is what
 * makes the deployment story an adapter swap rather than a rewrite.
 */
public interface TripLogSource {
    String globFor(Feed feed);
}
```

`service/src/main/java/com/signaldesk/ingest/LocalTripLogSource.java`:

```java
package com.signaldesk.ingest;

import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class LocalTripLogSource implements TripLogSource {

    private final Path dir;

    public LocalTripLogSource(@Value("${signaldesk.fixture-dir}") String dir) {
        this.dir = Path.of(dir);
    }

    @Override
    public String globFor(Feed feed) {
        return dir.resolve(feed.fileName()).toAbsolutePath().normalize().toString();
    }
}
```

`service/src/main/java/com/signaldesk/ingest/RejectRecord.java`:

```java
package com.signaldesk.ingest;

/** A quarantined row. This is a finding, not a log line. */
public record RejectRecord(Feed feed, long line, String column, String error, String raw) {}
```

- [ ] **Step 4: Write the loader**

`service/src/main/java/com/signaldesk/ingest/DuckDbLoader.java`:

```java
package com.signaldesk.ingest;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;

/**
 * One tolerant view per feed.
 *
 * ignore_errors is FORBIDDEN here: it has a known defect where it silently drops
 * valid rows, and silent loss is the opposite of what this product claims.
 * store_rejects keeps every failure inspectable.
 */
public class DuckDbLoader {

    private final Connection conn;
    private final TripLogSource source;
    private final Map<Feed, Long> loaded = new EnumMap<>(Feed.class);
    private final Map<Feed, List<RejectRecord>> rejects = new EnumMap<>(Feed.class);

    public DuckDbLoader(Connection conn, TripLogSource source) {
        this.conn = conn;
        this.source = source;
    }

    public void loadAll() {
        for (Feed feed : Feed.values()) {
            load(feed);
        }
    }

    public void load(Feed feed) {
        try {
            materialise(feed);
            loaded.put(feed, countRows(feed));
            rejects.put(feed, readRejects(feed));
        } catch (SQLException e) {
            throw new IngestException("failed to load feed " + feed, e);
        }
    }

    /**
     * Scan the CSV once through a tolerant reader, then materialise the result as
     * a TABLE.
     *
     * Why a table and not a view: a view over read_csv_auto(store_rejects = true)
     * is lazy, so every later query re-scans the file and re-writes the rejects
     * table. Two things then break. The rejects tables are per-feed here and are
     * never dropped, so a re-scan would double-count them; and every metric query
     * would re-parse the CSV, which contradicts the sub-millisecond latency
     * argument the data-layer choice rests on. Materialising costs one pass and
     * ~8k rows of memory.
     */
    private void materialise(Feed feed) throws SQLException {
        String scanView = feed.viewName() + "_scan";
        String errorsTable = "reject_errors_" + feed.viewName();
        String scansTable = "reject_scans_" + feed.viewName();

        // The glob is interpolated rather than bound: read_csv_auto's first
        // argument is resolved at bind time in a way that rejects a parameter in
        // some driver versions. It comes from TripLogSource, never from a user or
        // the model, so there is no injection surface — and the model's four tools
        // deliberately expose no path to this method at all.
        String createScan = """
                CREATE OR REPLACE VIEW %s AS
                SELECT * FROM read_csv_auto(
                  '%s',
                  union_by_name = true,
                  store_rejects = true,
                  rejects_table = '%s',
                  rejects_scan  = '%s'
                )
                """.formatted(scanView, source.globFor(feed).replace("'", "''"),
                              errorsTable, scansTable);

        try (Statement s = conn.createStatement()) {
            s.execute("DROP TABLE IF EXISTS " + errorsTable);
            s.execute("DROP TABLE IF EXISTS " + scansTable);
            s.execute(createScan);
            // Forces exactly one scan, which is what populates the rejects tables.
            s.execute("CREATE OR REPLACE TABLE " + feed.viewName()
                    + " AS SELECT * FROM " + scanView);
            s.execute("DROP VIEW IF EXISTS " + scanView);
        }
    }

    private long countRows(Feed feed) throws SQLException {
        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery("SELECT count(*) FROM " + feed.viewName())) {
            rs.next();
            return rs.getLong(1);
        }
    }

    private List<RejectRecord> readRejects(Feed feed) throws SQLException {
        List<RejectRecord> out = new ArrayList<>();
        // Per-feed table, so one feed's rejects can never be attributed to another.
        String sql = """
                SELECT line, coalesce(column_name, '') AS column_name,
                       coalesce(error_message, '') AS error_message,
                       coalesce(csv_line, '') AS csv_line
                FROM reject_errors_%s
                """.formatted(feed.viewName());
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                out.add(new RejectRecord(feed, rs.getLong("line"), rs.getString("column_name"),
                        rs.getString("error_message"), rs.getString("csv_line")));
            }
        } catch (SQLException e) {
            if (e.getMessage() != null && e.getMessage().contains("reject_errors_")) {
                // DuckDB only creates the rejects table when there is a reject.
                return List.of();
            }
            throw e;
        }
        return out;
    }

    public long rowsLoaded(Feed feed) {
        return loaded.getOrDefault(feed, 0L);
    }

    public List<RejectRecord> rejects(Feed feed) {
        return rejects.getOrDefault(feed, List.of());
    }

    public static class IngestException extends RuntimeException {
        public IngestException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
```

- [ ] **Step 5: Run the tests**

Run: `./scripts/mvn.sh -q test -Dtest=DuckDbLoaderTest`
Expected: PASS, 2 tests.

The exact rejects-table column names vary between DuckDB versions. If the query
fails, run a rejecting load then `duckdb -c "DESCRIBE reject_errors_trips"` and
correct the projection. Do not fall back to `SELECT *` and positional indexes.

- [ ] **Step 6: Add the forbidden-flag guard**

```java
    @Test
    void noViewIsCreatedWithIgnoreErrors() throws Exception {
        String source = Files.readString(
                Path.of("src/main/java/com/signaldesk/ingest/DuckDbLoader.java"));
        assertThat(source)
                .as("ignore_errors silently drops VALID rows; store_rejects is the only tolerance allowed")
                .doesNotContain("ignore_errors");
    }
```

A grep-as-a-test, because this is a constraint a future edit would violate
innocently and no behavioural test would catch.

- [ ] **Step 7: Wire the DataSource bean**

Create `service/src/main/java/com/signaldesk/ingest/DuckDbConfig.java`:

```java
package com.signaldesk.ingest;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class DuckDbConfig {

    /** In-process, in-memory. No database to stand up, no persistent disk. */
    @Bean
    public Connection duckDbConnection() throws SQLException {
        return DriverManager.getConnection("jdbc:duckdb:");
    }

    @Bean
    public DuckDbLoader duckDbLoader(Connection conn, TripLogSource source) {
        DuckDbLoader loader = new DuckDbLoader(conn, source);
        loader.loadAll();
        return loader;
    }
}
```

- [ ] **Step 8: Run the whole suite and confirm the real fixture loads**

Run: `./scripts/mvn.sh -q test`
Expected: PASS. The `@SpringBootTest` context now loads the committed fixture,
so a broken glob or a missing file fails here.

- [ ] **Step 9: Break-it-to-prove-it**

Remove `store_rejects = true` (and the two `rejects_*` lines) from `materialise`,
rerun. Expected: `aMalformedRowIsQuarantinedAndCountedRatherThanDropped` FAILS —
the load errors out entirely. Restore. Then remove `union_by_name = true`, rerun.
Expected: `unionByNameMergesTwoFilesWithDifferentColumnSets` FAILS. Restore.

Then prove the reason a table replaced a view: change the
`CREATE OR REPLACE TABLE` back to `CREATE OR REPLACE VIEW`, add a second query of
`trips` after the load, and rerun. Expected: the reject count doubles or the
second query errors, because a lazy view re-scans the CSV and re-writes the
rejects table. Restore. This is the defect the pre-flight scan caught; keep the
test that would catch it again:

```java
    @Test
    void aSecondQueryOfALoadedFeedDoesNotRescanOrDoubleCountRejects(@TempDir Path dir)
            throws Exception {
        Files.writeString(dir.resolve("trips.csv"), """
                trip_id,vendor_id,scheduled_at
                T000001,V01,100
                T000002,V01,200,UNEXPECTED_EXTRA_FIELD
                """);
        DuckDbLoader loader = new DuckDbLoader(conn, feed -> dir.resolve(feed.fileName()).toString());
        loader.load(Feed.TRIPS);

        int firstRejects = loader.rejects(Feed.TRIPS).size();
        try (Statement s = conn.createStatement()) {
            s.executeQuery("SELECT count(*) FROM trips").close();
            s.executeQuery("SELECT count(*) FROM trips").close();
        }

        assertThat(loader.rejects(Feed.TRIPS)).hasSize(firstRejects);
        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery("SELECT count(*) FROM reject_errors_trips")) {
            rs.next();
            assertThat(rs.getLong(1))
                    .as("a re-query must not re-scan the CSV and re-append rejects")
                    .isEqualTo(firstRejects);
        }
    }
```

- [ ] **Step 10: Commit**

```bash
git add service
git commit -m "feat(ingest): tolerant DuckDB views with a rejects quarantine, behind a pluggable source"
```

---

### Task 4: Gap register and the per-feed confidence figure (~0 h 30)

**Files:**
- Create: `service/src/main/java/com/signaldesk/ingest/FeedHealth.java`
- Create: `service/src/main/java/com/signaldesk/ingest/GapRegister.java`
- Test: `service/src/test/java/com/signaldesk/ingest/GapRegisterTest.java`

**Interfaces:**
- Consumes: `DuckDbLoader`, `Feed`, a DuckDB `Connection`.
- Produces:
  - `record FeedHealth(Feed feed, long rowsLoaded, long rowsRejected, long unmatchedKeys, long nullCriticalFields, double confidence)`
  - `GapRegister.assess()` returning `Map<Feed, FeedHealth>`
  - `GapRegister.confidenceFor(Feed)` — Tasks 7 and 9 read this to stamp every finding.

**Two definitions the spec leaves open, settled here.**

*Roster orphans are resolved against `feedback.employee_id`.* §3.2 calls them
"employees with no matching trip", but `trips` carries no `employee_id` — the
only feed that names an employee is `feedback`. So a roster row is unmatched when
its `employee_id` appears in no feedback row.

*`night_escort` is deliberately NOT a critical column of `trips`.* A dataset
missing the escort column must degrade `night_compliance`, not the on-time
figures. Per-feed confidence therefore ignores it, and Task 5 gives each metric
its own `requiredColumns` coverage check. A finding's confidence is
`feedConfidence × columnCoverage`.

- [ ] **Step 1: Write the failing tests**

`service/src/test/java/com/signaldesk/ingest/GapRegisterTest.java`:

```java
package com.signaldesk.ingest;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class GapRegisterTest {

    private Connection conn;

    @BeforeEach
    void open() throws Exception {
        conn = DriverManager.getConnection("jdbc:duckdb:");
    }

    @AfterEach
    void close() throws Exception {
        conn.close();
    }

    private GapRegister loadFrom(Path dir) {
        DuckDbLoader loader = new DuckDbLoader(conn, feed -> dir.resolve(feed.fileName()).toString());
        loader.loadAll();
        return new GapRegister(conn, loader);
    }

    private void writeCleanFixture(Path dir) throws Exception {
        Files.writeString(dir.resolve("trips.csv"), """
                trip_id,vendor_id,site_id,shift,mode,direction,scheduled_at,actual_at,night_escort
                T1,V01,SITE1,S1,cab,login,1000,1200,true
                T2,V01,SITE1,S1,cab,login,2000,2100,true
                """);
        Files.writeString(dir.resolve("costs.csv"), """
                trip_id,vendor_id,total_inr
                T1,V01,300
                T2,V01,310
                """);
        Files.writeString(dir.resolve("feedback.csv"), """
                trip_id,employee_id,rating,comment,language
                T1,E1,5,"fine",en
                T2,E2,4,"ok",en
                """);
        Files.writeString(dir.resolve("roster.csv"), """
                employee_id,site_id,shift,date,expected
                E1,SITE1,S1,1000,1
                E2,SITE1,S1,1000,1
                """);
        Files.writeString(dir.resolve("gps_pings.csv"), "trip_id,ts,lat,lng\nT1,1000,12.9,77.5\n");
        Files.writeString(dir.resolve("delays.csv"), "trip_id,reason_code,minutes,recorded_at\n");
    }

    @Test
    void confidenceIsExactlyOneOnCleanInput(@TempDir Path dir) throws Exception {
        writeCleanFixture(dir);

        Map<Feed, FeedHealth> health = loadFrom(dir).assess();

        assertThat(health.get(Feed.TRIPS).confidence()).isEqualTo(1.0);
        assertThat(health.get(Feed.COSTS).confidence()).isEqualTo(1.0);
        assertThat(health.get(Feed.ROSTER).confidence()).isEqualTo(1.0);
    }

    @Test
    void confidenceFallsWhenAnUnmatchedKeyIsInjected(@TempDir Path dir) throws Exception {
        writeCleanFixture(dir);
        Files.writeString(dir.resolve("costs.csv"), """
                trip_id,vendor_id,total_inr
                T1,V01,300
                T990001,V01,310
                """);

        FeedHealth costs = loadFrom(dir).assess().get(Feed.COSTS);

        assertThat(costs.unmatchedKeys()).isEqualTo(1);
        assertThat(costs.confidence()).isEqualTo(0.5);
    }

    @Test
    void confidenceFallsWhenAMalformedRowIsInjected(@TempDir Path dir) throws Exception {
        writeCleanFixture(dir);
        Files.writeString(dir.resolve("costs.csv"), """
                trip_id,vendor_id,total_inr
                T1,V01,300
                T2,V01,310,UNEXPECTED_EXTRA_FIELD
                """);

        FeedHealth costs = loadFrom(dir).assess().get(Feed.COSTS);

        assertThat(costs.rowsRejected()).isEqualTo(1);
        assertThat(costs.confidence()).isEqualTo(0.5);
    }

    @Test
    void confidenceIsClampedToZeroRatherThanGoingNegative(@TempDir Path dir) throws Exception {
        writeCleanFixture(dir);
        Files.writeString(dir.resolve("costs.csv"), """
                trip_id,vendor_id,total_inr
                T990001,V01,300
                T990002,,310
                """);

        FeedHealth costs = loadFrom(dir).assess().get(Feed.COSTS);

        assertThat(costs.confidence()).isBetween(0.0, 1.0);
    }
}
```

Three separate degradations rather than one: the confidence formula sums three
independent counters, and a test that only injects one of them passes under an
implementation that ignores the other two.

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=GapRegisterTest`
Expected: FAIL — `cannot find symbol: class GapRegister`.

- [ ] **Step 3: Write FeedHealth**

`service/src/main/java/com/signaldesk/ingest/FeedHealth.java`:

```java
package com.signaldesk.ingest;

/**
 * What a feed could not tell us, as a number. A number the agent is unsure about
 * must say so, so every finding derived from a feed carries this confidence.
 */
public record FeedHealth(
        Feed feed,
        long rowsLoaded,
        long rowsRejected,
        long unmatchedKeys,
        long nullCriticalFields,
        double confidence) {

    public static FeedHealth of(Feed feed, long rowsLoaded, long rowsRejected,
                                long unmatchedKeys, long nullCriticalFields) {
        long considered = rowsLoaded + rowsRejected;
        double raw = considered == 0
                ? 1.0
                : 1.0 - (rowsRejected + unmatchedKeys + nullCriticalFields) / (double) considered;
        double clamped = Math.max(0.0, Math.min(1.0, raw));
        return new FeedHealth(feed, rowsLoaded, rowsRejected, unmatchedKeys,
                nullCriticalFields, clamped);
    }

    /** Below this the narrative must mention the uncertainty (spec §4.3). */
    public boolean mustBeDisclosed() {
        return confidence < 0.9;
    }
}
```

- [ ] **Step 4: Write the gap register**

`service/src/main/java/com/signaldesk/ingest/GapRegister.java`:

```java
package com.signaldesk.ingest;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class GapRegister {

    /**
     * Critical columns per feed. night_escort is deliberately absent from TRIPS:
     * a dataset without it must degrade night_compliance, not the on-time figures.
     */
    private static final Map<Feed, List<String>> CRITICAL = Map.of(
            Feed.TRIPS, List.of("trip_id", "vendor_id", "scheduled_at"),
            Feed.GPS_PINGS, List.of("trip_id", "ts"),
            Feed.DELAYS, List.of("trip_id", "minutes"),
            Feed.COSTS, List.of("trip_id", "total_inr"),
            Feed.FEEDBACK, List.of("trip_id", "rating"),
            Feed.ROSTER, List.of("employee_id", "date"));

    /** How each feed's foreign key is checked, and against what. */
    private static final Map<Feed, String> UNMATCHED_SQL = Map.of(
            Feed.GPS_PINGS, "SELECT count(*) FROM gps_pings x WHERE x.trip_id NOT IN (SELECT trip_id FROM trips)",
            Feed.DELAYS, "SELECT count(*) FROM delays x WHERE x.trip_id NOT IN (SELECT trip_id FROM trips)",
            Feed.COSTS, "SELECT count(*) FROM costs x WHERE x.trip_id NOT IN (SELECT trip_id FROM trips)",
            Feed.FEEDBACK, "SELECT count(*) FROM feedback x WHERE x.trip_id NOT IN (SELECT trip_id FROM trips)",
            // trips carries no employee_id, so a roster orphan is resolved against feedback
            Feed.ROSTER, "SELECT count(*) FROM roster x WHERE x.employee_id NOT IN (SELECT employee_id FROM feedback)");

    private final Connection conn;
    private final DuckDbLoader loader;
    private Map<Feed, FeedHealth> cached;

    public GapRegister(Connection conn, DuckDbLoader loader) {
        this.conn = conn;
        this.loader = loader;
    }

    public Map<Feed, FeedHealth> assess() {
        Map<Feed, FeedHealth> out = new EnumMap<>(Feed.class);
        for (Feed feed : Feed.values()) {
            out.put(feed, FeedHealth.of(feed,
                    loader.rowsLoaded(feed),
                    loader.rejects(feed).size(),
                    countUnmatched(feed),
                    countNullCritical(feed)));
        }
        cached = out;
        return out;
    }

    public double confidenceFor(Feed feed) {
        if (cached == null) {
            assess();
        }
        FeedHealth h = cached.get(feed);
        return h == null ? 0.0 : h.confidence();
    }

    private long countUnmatched(Feed feed) {
        String sql = UNMATCHED_SQL.get(feed);
        return sql == null ? 0L : scalar(sql);
    }

    private long countNullCritical(Feed feed) {
        List<String> cols = CRITICAL.getOrDefault(feed, List.of());
        List<String> present = presentColumns(feed);
        String predicate = cols.stream()
                .filter(present::contains)
                .map(c -> c + " IS NULL")
                .reduce((a, b) -> a + " OR " + b)
                .orElse(null);
        if (predicate == null) {
            // Every critical column is absent from the file entirely: every row
            // is critically incomplete.
            return loader.rowsLoaded(feed);
        }
        long missingColumns = cols.stream().filter(c -> !present.contains(c)).count();
        long rowsWithNulls = scalar("SELECT count(*) FROM " + feed.viewName() + " WHERE " + predicate);
        return missingColumns > 0 ? loader.rowsLoaded(feed) : rowsWithNulls;
    }

    private List<String> presentColumns(Feed feed) {
        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery("SELECT * FROM " + feed.viewName() + " LIMIT 0")) {
            int n = rs.getMetaData().getColumnCount();
            List<String> cols = new java.util.ArrayList<>(n);
            for (int i = 1; i <= n; i++) {
                cols.add(rs.getMetaData().getColumnName(i));
            }
            return cols;
        } catch (SQLException e) {
            return List.of();
        }
    }

    private long scalar(String sql) {
        try (Statement s = conn.createStatement(); ResultSet rs = s.executeQuery(sql)) {
            rs.next();
            return rs.getLong(1);
        } catch (SQLException e) {
            return 0L;
        }
    }
}
```

- [ ] **Step 5: Run the tests**

Run: `./scripts/mvn.sh -q test -Dtest=GapRegisterTest`
Expected: PASS, 4 tests.

- [ ] **Step 6: Log the real fixture's health, and pin it**

Add:

```java
    @Test
    void theCommittedFixtureHasTheHealthProfileTheDemoNarrativeNeeds() {
        Path committed = Path.of("..", "data", "fixture");
        assumeTrue(Files.isDirectory(committed), "committed fixture not present");
        DuckDbLoader loader = new DuckDbLoader(conn, feed ->
                committed.resolve(feed.fileName()).toAbsolutePath().toString());
        loader.loadAll();

        Map<Feed, FeedHealth> health = new GapRegister(conn, loader).assess();
        health.values().forEach(h -> System.out.printf(
                "MEASURED %s loaded=%d rejected=%d unmatched=%d nullCritical=%d confidence=%.4f%n",
                h.feed(), h.rowsLoaded(), h.rowsRejected(), h.unmatchedKeys(),
                h.nullCriticalFields(), h.confidence()));

        // Pinned after measuring. Update the comment, not just the number, if the
        // fixture is regenerated.
        assertThat(health.get(Feed.TRIPS).confidence()).isGreaterThan(0.0);
        assertThat(health.get(Feed.COSTS).confidence()).isGreaterThan(0.0);
    }
```

Run it, read the `MEASURED` lines, then replace the two `isGreaterThan(0.0)`
assertions with `isBetween(x, y)` bands set at roughly ±0.05 around the measured
values, and record the measured figures in a comment above them. **Do not invent
the band.** At least one feed should land below 0.9 so the disclosure path in
Task 11 has something to disclose; if none does, the planted faults are too
sparse and Task 2's rates need raising.

- [ ] **Step 7: Break-it-to-prove-it**

Change `FeedHealth.of` to ignore `unmatchedKeys`, rerun. Expected:
`confidenceFallsWhenAnUnmatchedKeyIsInjected` FAILS. Restore. Repeat for
`rowsRejected` and confirm the malformed test fails. Restore.

- [ ] **Step 8: Commit**

```bash
git add service
git commit -m "feat(ingest): gap register producing a per-feed confidence figure"
```

---

### Task 5: Metric registry — the governed vocabulary (~1 h 00)

**Files:**
- Create: `service/src/main/java/com/signaldesk/registry/Direction.java`, `ReferenceKind.java`, `Dimension.java`, `Slice.java`, `Window.java`, `MetricConstants.java`, `Metric.java`, `MetricRegistry.java`, `MetricRepository.java`, `DuckDbMetricRepository.java`
- Test: `service/src/test/java/com/signaldesk/registry/MetricRegistryTest.java`
- Test: `service/src/test/java/com/signaldesk/registry/DuckDbMetricRepositoryTest.java`

**Interfaces:**
- Consumes: DuckDB `Connection`, `GapRegister`, `Feed`.
- Produces:
  - `enum Direction { HIGHER, LOWER }`
  - `enum ReferenceKind { TREND, TARGET, PEER }`
  - `enum Dimension { VENDOR, SITE, SHIFT, MODE, DIRECTION, NONE }` with `String column()`
  - `record Slice(Dimension dim, String value)` with `Slice.all()`
  - `record Window(long startMs, long endMs, String label)` with `Window.weekEnding(long)`, `Window shiftedBack(int weeks)`
  - `record Metric(String id, String label, String unit, Direction better, String sql, List<ReferenceKind> refs, Double target, boolean hardTarget, Feed source, List<String> requiredColumns)`
  - `MetricRegistry.all()`, `MetricRegistry.active()`, `MetricRegistry.byId(String)`, `MetricRegistry.ids()`
  - `interface MetricRepository { OptionalDouble evaluate(Metric, Slice, Window); double coverage(Metric, Slice, Window); List<String> distinctValues(Dimension, Window); }`

**All six metrics are defined here**, per proposal decision 7a — getting the
shape wrong costs the day, adding rules later costs minutes. Only metrics 1–3 are
*active*; `signaldesk.metrics.active` widens in Tasks 20 and 19. `experience`
additionally needs the `feedback_normalised` table that Task 21 creates, so its
SQL test skips until then.

- [ ] **Step 1: Write the failing registry tests**

`service/src/test/java/com/signaldesk/registry/MetricRegistryTest.java`:

```java
package com.signaldesk.registry;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import org.junit.jupiter.api.Test;

class MetricRegistryTest {

    private final MetricRegistry registry = new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));

    @Test
    void holdsAllSixMetricsFromTheStart() {
        assertThat(registry.ids())
                .containsExactly("ota", "sla_breach", "vendor_ota",
                        "cost_per_trip", "night_compliance", "experience");
    }

    @Test
    void otaIsFirstBecauseItIsTheStatementsOwnWorkedExample() {
        assertThat(registry.all().get(0).id()).isEqualTo("ota");
    }

    @Test
    void onlyTheConfiguredMetricsAreActive() {
        assertThat(registry.active()).extracting(Metric::id)
                .containsExactly("ota", "sla_breach", "vendor_ota");
    }

    @Test
    void everyMetricDeclaringATargetActuallyHasOne() {
        for (Metric m : registry.all()) {
            if (m.refs().contains(ReferenceKind.TARGET)) {
                assertThat(m.target()).as("metric %s declares TARGET", m.id()).isNotNull();
            } else {
                assertThat(m.target()).as("metric %s does not declare TARGET", m.id()).isNull();
            }
        }
    }

    @Test
    void everyMetricDeclaresAtLeastOneReferencePoint() {
        // The mandatory bar is contextualisation against at least one reference
        // point. Satisfied by construction, not by a feature.
        assertThat(registry.all()).allSatisfy(m ->
                assertThat(m.refs()).as("metric %s", m.id()).isNotEmpty());
    }

    @Test
    void onlyNightComplianceHasAHardTarget() {
        assertThat(registry.all()).filteredOn(Metric::hardTarget)
                .extracting(Metric::id).containsExactly("night_compliance");
    }

    @Test
    void aMetricWithATargetButNoTargetReferenceIsRejected() {
        assertThatThrownBy(() -> new Metric("bad", "Bad", "%", Direction.HIGHER,
                "SELECT 1", List.of(ReferenceKind.TREND), 90.0, false,
                com.signaldesk.ingest.Feed.TRIPS, List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("TARGET");
    }

    @Test
    void theNightConstantsAgreeWithTheFixtureGeneratorsNightRule() {
        // The generator and this SQL disagreed in an earlier draft: the generator
        // hardcoded "S3 logout is night" while the predicate tested the IST hour,
        // and S3 logout at 06:00 IST satisfied neither — night_compliance matched
        // zero rows. Task 2 pins the generator side; this pins the agreement.
        assertThat(MetricConstants.NIGHT_START_HOUR_IST)
                .isEqualTo(FixtureGenerator.MetricNight.START_HOUR);
        assertThat(MetricConstants.NIGHT_END_HOUR_IST)
                .isEqualTo(FixtureGenerator.MetricNight.END_HOUR);
        assertThat(MetricConstants.IST_OFFSET_MS).isEqualTo(FixtureGenerator.IST_OFFSET_MS);
    }

    @Test
    void anUnknownMetricIdIsRejectedByNameWithTheValidOnesListed() {
        assertThatThrownBy(() -> registry.byId("on_time_arrival"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("on_time_arrival")
                .hasMessageContaining("ota");
    }
}
```

The last test matters more than it looks: it is the guarantee that Task 22's
tools refuse an unknown id *with the valid values named*, rather than guessing
or passing it to SQL.

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=MetricRegistryTest`
Expected: FAIL — `cannot find symbol: class MetricRegistry`.

- [ ] **Step 3: Write the enums, slice, window and constants**

`Direction.java`:

```java
package com.signaldesk.registry;

public enum Direction { HIGHER, LOWER }
```

`ReferenceKind.java`:

```java
package com.signaldesk.registry;

public enum ReferenceKind { TREND, TARGET, PEER }
```

`Dimension.java`:

```java
package com.signaldesk.registry;

/**
 * The enumerated slice dimensions. The model selects from these; it never
 * composes a join, and the column names below are the only ones that ever reach
 * SQL — values are always bound as parameters.
 */
public enum Dimension {
    VENDOR("t.vendor_id"),
    SITE("t.site_id"),
    SHIFT("t.shift"),
    MODE("t.mode"),
    DIRECTION("t.direction"),
    NONE(null);

    private final String column;

    Dimension(String column) {
        this.column = column;
    }

    public String column() {
        if (this == NONE) {
            throw new IllegalStateException("Dimension.NONE has no column");
        }
        return column;
    }

    public static Dimension parse(String raw) {
        for (Dimension d : values()) {
            if (d.name().equalsIgnoreCase(raw)) {
                return d;
            }
        }
        throw new IllegalArgumentException(
                "unknown dimension '" + raw + "'; valid values are "
                        + java.util.Arrays.toString(values()));
    }
}
```

`Slice.java`:

```java
package com.signaldesk.registry;

public record Slice(Dimension dim, String value) {

    public Slice {
        if (dim == Dimension.NONE && value != null) {
            throw new IllegalArgumentException("Dimension.NONE must carry a null value");
        }
        if (dim != Dimension.NONE && (value == null || value.isBlank())) {
            throw new IllegalArgumentException("dimension " + dim + " requires a value");
        }
    }

    public static Slice all() {
        return new Slice(Dimension.NONE, null);
    }

    public String label() {
        return dim == Dimension.NONE ? "overall" : dim.name().toLowerCase() + " " + value;
    }
}
```

`Window.java`:

```java
package com.signaldesk.registry;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

/** Half-open: [startMs, endMs). */
public record Window(long startMs, long endMs, String label) {

    public static final long WEEK_MS = 7L * 86_400_000L;

    public Window {
        if (endMs <= startMs) {
            throw new IllegalArgumentException("window end must be after start");
        }
    }

    /** The seven days ending (exclusive) at endMs. */
    public static Window weekEnding(long endMs) {
        return new Window(endMs - WEEK_MS, endMs, isoRange(endMs - WEEK_MS, endMs));
    }

    /** The same-length window, moved back n whole windows. */
    public Window shiftedBack(int n) {
        long len = endMs - startMs;
        long newEnd = endMs - n * len;
        return new Window(newEnd - len, newEnd, isoRange(newEnd - len, newEnd));
    }

    private static String isoRange(long start, long end) {
        DateTimeFormatter f = DateTimeFormatter.ISO_LOCAL_DATE.withZone(ZoneOffset.UTC);
        return f.format(Instant.ofEpochMilli(start)) + ".." + f.format(Instant.ofEpochMilli(end - 1));
    }
}
```

`MetricConstants.java`:

```java
package com.signaldesk.registry;

/**
 * The thresholds the spec names the metrics for but does not define. They live
 * here, once, so the real dataset can move them in one edit.
 */
public final class MetricConstants {

    /** On time means arriving within this grace period of schedule. */
    public static final long ON_TIME_GRACE_MS = 5 * 60_000L;
    /** An SLA breach is arriving later than this. */
    public static final long SLA_BREACH_MS = 15 * 60_000L;
    /** Epoch ms are absolute; "night trip" is local. */
    public static final long IST_OFFSET_MS = 19_800_000L;
    public static final int NIGHT_START_HOUR_IST = 22;
    public static final int NIGHT_END_HOUR_IST = 6;

    private MetricConstants() {}
}
```

- [ ] **Step 4: Write the Metric record**

`Metric.java`:

```java
package com.signaldesk.registry;

import com.signaldesk.ingest.Feed;
import java.util.List;

/**
 * A metric definition. The SQL here is the ONLY SQL in the application outside
 * the ingest layer: nothing else queries raw tables.
 *
 * The SQL must aggregate to exactly one number, bind the window as two
 * parameters in order (startMs, endMs), and contain the token {{SLICE}} where a
 * slice predicate is spliced in. Slice values are always bound, never
 * interpolated.
 */
public record Metric(
        String id,
        String label,
        String unit,
        Direction better,
        String sql,
        List<ReferenceKind> refs,
        Double target,
        boolean hardTarget,
        Feed source,
        List<String> requiredColumns) {

    public Metric {
        boolean declaresTarget = refs.contains(ReferenceKind.TARGET);
        if (declaresTarget && target == null) {
            throw new IllegalArgumentException(
                    "metric " + id + " declares ReferenceKind.TARGET but has no target value");
        }
        if (!declaresTarget && target != null) {
            throw new IllegalArgumentException(
                    "metric " + id + " has a target but does not declare ReferenceKind.TARGET");
        }
        if (hardTarget && target == null) {
            throw new IllegalArgumentException("metric " + id + " has a hard target but no target value");
        }
        if (!sql.contains("{{SLICE}}")) {
            throw new IllegalArgumentException("metric " + id + " SQL has no {{SLICE}} token");
        }
        refs = List.copyOf(refs);
        requiredColumns = List.copyOf(requiredColumns);
    }
}
```

- [ ] **Step 5: Write the registry with all six metrics**

`MetricRegistry.java`:

```java
package com.signaldesk.registry;

import com.signaldesk.ingest.Feed;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class MetricRegistry {

    private static final String OTA_SQL = """
            SELECT 100.0 * sum(CASE WHEN t.actual_at <= t.scheduled_at + %d THEN 1 ELSE 0 END)
                   / nullif(count(*), 0)
            FROM trips t
            WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
              AND t.actual_at IS NOT NULL
              {{SLICE}}
            """.formatted(MetricConstants.ON_TIME_GRACE_MS);

    private static final String SLA_SQL = """
            SELECT 100.0 * sum(CASE WHEN t.actual_at > t.scheduled_at + %d THEN 1 ELSE 0 END)
                   / nullif(count(*), 0)
            FROM trips t
            WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
              AND t.actual_at IS NOT NULL
              {{SLICE}}
            """.formatted(MetricConstants.SLA_BREACH_MS);

    private static final String COST_SQL = """
            SELECT avg(c.total_inr)
            FROM costs c JOIN trips t ON t.trip_id = c.trip_id
            WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
              {{SLICE}}
            """;

    private static final String NIGHT_SQL = """
            SELECT 100.0 * sum(CASE WHEN t.night_escort THEN 1 ELSE 0 END)
                   / nullif(count(*), 0)
            FROM trips t
            WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
              AND t.direction = 'logout'
              AND (extract(hour FROM epoch_ms(t.scheduled_at + %d)) >= %d
                   OR extract(hour FROM epoch_ms(t.scheduled_at + %d)) < %d)
              {{SLICE}}
            """.formatted(MetricConstants.IST_OFFSET_MS, MetricConstants.NIGHT_START_HOUR_IST,
                          MetricConstants.IST_OFFSET_MS, MetricConstants.NIGHT_END_HOUR_IST);

    /**
     * The sentiment column is written by Task 21's normaliser from a deterministic
     * Java lexicon over the translated comment. The model does language; this
     * arithmetic is unit-tested Java.
     */
    private static final String EXPERIENCE_SQL = """
            SELECT avg(least(5.0, greatest(1.0, f.rating + 0.5 * f.sentiment)))
            FROM feedback_normalised f JOIN trips t ON t.trip_id = f.trip_id
            WHERE t.scheduled_at >= ? AND t.scheduled_at < ?
              {{SLICE}}
            """;

    private final List<Metric> metrics = List.of(
            new Metric("ota", "On-time arrival", "%", Direction.HIGHER, OTA_SQL,
                    List.of(ReferenceKind.TREND, ReferenceKind.TARGET), 90.0, false,
                    Feed.TRIPS, List.of("actual_at", "scheduled_at")),
            new Metric("sla_breach", "SLA breach rate", "%", Direction.LOWER, SLA_SQL,
                    List.of(ReferenceKind.TARGET), 10.0, false,
                    Feed.TRIPS, List.of("actual_at", "scheduled_at")),
            new Metric("vendor_ota", "Vendor on-time share", "%", Direction.HIGHER, OTA_SQL,
                    List.of(ReferenceKind.TREND, ReferenceKind.PEER), null, false,
                    Feed.TRIPS, List.of("actual_at", "scheduled_at", "vendor_id")),
            new Metric("cost_per_trip", "Cost per trip", "INR", Direction.LOWER, COST_SQL,
                    List.of(ReferenceKind.TREND, ReferenceKind.PEER), null, false,
                    Feed.COSTS, List.of("total_inr")),
            new Metric("night_compliance", "Night-trip compliance", "%", Direction.HIGHER, NIGHT_SQL,
                    List.of(ReferenceKind.TARGET), 100.0, true,
                    Feed.TRIPS, List.of("night_escort")),
            new Metric("experience", "Employee experience", "score", Direction.HIGHER, EXPERIENCE_SQL,
                    List.of(ReferenceKind.TREND), null, false,
                    Feed.FEEDBACK, List.of("rating")));

    private final List<String> activeIds;

    public MetricRegistry(
            @Value("${signaldesk.metrics.active:ota,sla_breach,vendor_ota}") List<String> activeIds) {
        this.activeIds = List.copyOf(activeIds);
        activeIds.forEach(this::byId);   // fail fast on a typo in configuration
    }

    public List<Metric> all() {
        return metrics;
    }

    /** Metrics 4-6 land after the hour-seven checkpoint; this is how they are gated. */
    public List<Metric> active() {
        return metrics.stream().filter(m -> activeIds.contains(m.id())).toList();
    }

    public List<String> ids() {
        return metrics.stream().map(Metric::id).toList();
    }

    public Metric byId(String id) {
        return metrics.stream().filter(m -> m.id().equals(id)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "unknown metric id '" + id + "'; valid ids are " + ids()));
    }
}
```

Add to `application.yaml`, under `signaldesk`:

```yaml
  metrics:
    active: ota,sla_breach,vendor_ota
```

- [ ] **Step 6: Run the registry tests**

Run: `./scripts/mvn.sh -q test -Dtest=MetricRegistryTest`
Expected: PASS, 9 tests.

`theNightConstantsAgreeWithTheFixtureGeneratorsNightRule` needs
`FixtureGenerator`'s package-private `MetricNight` and `IST_OFFSET_MS`. Put this
one test in `com.signaldesk.fixture` (as `NightRuleAgreementTest`) rather than
widening `FixtureGenerator`'s visibility — the assertion belongs to whichever
package can see both, and the fixture package already imports nothing from the
registry at runtime.

- [ ] **Step 7: Write the failing repository tests**

`service/src/test/java/com/signaldesk/registry/DuckDbMetricRepositoryTest.java`:

```java
package com.signaldesk.registry;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.signaldesk.fixture.FixtureGenerator;
import com.signaldesk.ingest.DuckDbLoader;
import com.signaldesk.ingest.Feed;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.List;
import java.util.OptionalDouble;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class DuckDbMetricRepositoryTest {

    private Connection conn;
    private DuckDbMetricRepository repo;
    private final MetricRegistry registry =
            new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));
    private final Window window = Window.weekEnding(FixtureGenerator.windowEnd());

    @BeforeEach
    void loadTheCommittedFixture() throws Exception {
        Path dir = Path.of("..", "data", "fixture");
        assumeTrue(Files.isDirectory(dir), "committed fixture not present");
        conn = DriverManager.getConnection("jdbc:duckdb:");
        new DuckDbLoader(conn, feed -> dir.resolve(feed.fileName()).toAbsolutePath().toString())
                .loadAll();
        repo = new DuckDbMetricRepository(conn);
    }

    @AfterEach
    void close() throws Exception {
        conn.close();
    }

    @Test
    void everyMetricReturnsExactlyOneNumberForTheUnslicedWindow() {
        for (Metric m : registry.all()) {
            if (m.id().equals("experience")) {
                continue;   // needs Task 21's feedback_normalised table
            }
            OptionalDouble v = repo.evaluate(m, Slice.all(), window);
            assertThat(v.isPresent()).as("metric %s returned no value", m.id()).isTrue();
            assertThat(v.getAsDouble()).as("metric %s", m.id()).isFinite();
        }
    }

    @Test
    void everyMetricReturnsOneNumberForEveryValidSliceDimension() {
        for (Metric m : registry.all()) {
            if (m.id().equals("experience")) {
                continue;
            }
            for (Dimension dim : Dimension.values()) {
                if (dim == Dimension.NONE) {
                    continue;
                }
                List<String> values = repo.distinctValues(dim, window);
                assertThat(values).as("dimension %s has no values in the window", dim).isNotEmpty();
                OptionalDouble v = repo.evaluate(m, new Slice(dim, values.get(0)), window);
                assertThat(v).as("metric %s sliced by %s", m.id(), dim).isNotNull();
            }
        }
    }

    @Test
    void percentageMetricsStayInRange() {
        double ota = repo.evaluate(registry.byId("ota"), Slice.all(), window).orElseThrow();
        double sla = repo.evaluate(registry.byId("sla_breach"), Slice.all(), window).orElseThrow();
        assertThat(ota).isBetween(0.0, 100.0);
        assertThat(sla).isBetween(0.0, 100.0);
        System.out.printf("MEASURED unsliced ota=%.2f sla_breach=%.2f%n", ota, sla);
    }

    @Test
    void anEmptySliceYieldsNoValueRatherThanZero() {
        OptionalDouble v = repo.evaluate(registry.byId("ota"),
                new Slice(Dimension.VENDOR, "V_DOES_NOT_EXIST"), window);
        assertThat(v).as("an empty slice is a data gap, not a score of zero").isEmpty();
    }

    @Test
    void coverageIgnoresASliceColumnTheSourceTableDoesNotHave() {
        // feedback has no vendor_id. Coverage must fall back to the unsliced figure
        // rather than reporting 0.0, which would cap every such finding at WATCH.
        double coverage = repo.coverage(registry.byId("cost_per_trip"),
                new Slice(Dimension.SHIFT, "S1"), window);

        assertThat(coverage).as("costs has no shift column, so coverage is measured unsliced")
                .isGreaterThan(0.0);
    }

    @Test
    void anInvalidDimensionIsRejectedBeforeAnySqlIsBuilt() {
        assertThatThrownBy(() -> Dimension.parse("route"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("route")
                .hasMessageContaining("VENDOR");
    }

    @Test
    void theDegradingVendorIsVisiblyWorseThanAPeerInTheFinalWeek() {
        Metric vendorOta = registry.byId("vendor_ota");
        double bad = repo.evaluate(vendorOta,
                new Slice(Dimension.VENDOR, FixtureGenerator.DEGRADING_VENDOR), window).orElseThrow();
        double peer = repo.evaluate(vendorOta, new Slice(Dimension.VENDOR, "V03"), window).orElseThrow();
        System.out.printf("MEASURED vendor_ota V07=%.2f V03=%.2f%n", bad, peer);
        assertThat(bad).as("the planted regression must be discoverable through the registry")
                .isLessThan(peer - 10.0);
    }
}
```

`anEmptySliceYieldsNoValueRatherThanZero` is the guard against the most damaging
possible bug in this layer: a missing slice scoring 0% and breaching on a vendor
that simply did not operate that week.

- [ ] **Step 8: Write the repository interface and DuckDB implementation**

`MetricRepository.java`:

```java
package com.signaldesk.registry;

import java.util.List;
import java.util.OptionalDouble;

/**
 * The adapter seam. Swapping DuckDB for Athena or Aurora is an implementation of
 * this interface, not a rewrite — which is the answer to the multi-tenancy
 * objection, and it is demonstrable in the code rather than asserted on stage.
 */
public interface MetricRepository {

    /** Empty when the slice has no rows: a data gap, never a zero. */
    OptionalDouble evaluate(Metric metric, Slice slice, Window window);

    /** Fraction of rows in the slice where every required column is non-null. */
    double coverage(Metric metric, Slice slice, Window window);

    List<String> distinctValues(Dimension dim, Window window);

    /** The exact query that produced a value, for Finding.evidenceSql. */
    String evidenceSql(Metric metric, Slice slice, Window window);
}
```

`DuckDbMetricRepository.java`:

```java
package com.signaldesk.registry;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.OptionalDouble;
import org.springframework.stereotype.Component;

@Component
public class DuckDbMetricRepository implements MetricRepository {

    private final Connection conn;

    public DuckDbMetricRepository(Connection conn) {
        this.conn = conn;
    }

    @Override
    public OptionalDouble evaluate(Metric metric, Slice slice, Window window) {
        String sql = bindSlicePredicate(metric.sql(), slice);
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            int i = bindWindow(ps, window);
            bindSliceValue(ps, i, slice);
            try (ResultSet rs = ps.executeQuery()) {
                if (!rs.next()) {
                    return OptionalDouble.empty();
                }
                double v = rs.getDouble(1);
                return rs.wasNull() ? OptionalDouble.empty() : OptionalDouble.of(v);
            }
        } catch (SQLException e) {
            throw new MetricQueryException(
                    "metric " + metric.id() + " failed for slice " + slice.label(), e);
        }
    }

    @Override
    public double coverage(Metric metric, Slice slice, Window window) {
        if (metric.requiredColumns().isEmpty()) {
            return 1.0;
        }
        String table = metric.source().viewName();
        List<String> present = presentColumns(table);
        if (!present.containsAll(metric.requiredColumns())) {
            // A column the metric needs is absent from the dataset entirely.
            // The metric degrades; it does not lie.
            return 0.0;
        }
        String nonNull = metric.requiredColumns().stream()
                .map(c -> c + " IS NOT NULL")
                .reduce((a, b) -> a + " AND " + b)
                .orElse("TRUE");

        // Strip the "t." qualifier: this query is against the metric's SOURCE table,
        // which is not always aliased t. If that table has no such column — feedback
        // has no vendor_id — measure coverage UNSLICED rather than returning 0.0.
        // Returning 0.0 would cap every experience-by-vendor finding at WATCH with
        // cause LOW_CONFIDENCE, turning a modelling gap into a wall of noise. Column
        // absence among the metric's OWN requiredColumns still returns 0.0 above,
        // which is what deviation 6 needs.
        String sliceColumn = slice.dim() == Dimension.NONE
                ? null : slice.dim().column().substring(2);
        boolean sliceable = sliceColumn != null && present.contains(sliceColumn);
        String slicePredicate = sliceable ? " AND " + sliceColumn + " = ?" : "";

        String sql = "SELECT avg(CASE WHEN " + nonNull + " THEN 1.0 ELSE 0.0 END) FROM "
                + table + " WHERE TRUE" + slicePredicate;
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            if (sliceable) {
                ps.setString(1, slice.value());
            }
            try (ResultSet rs = ps.executeQuery()) {
                if (!rs.next()) {
                    return 0.0;
                }
                double v = rs.getDouble(1);
                return rs.wasNull() ? 0.0 : v;
            }
        } catch (SQLException e) {
            return 0.0;   // an unsliceable source degrades confidence, never fails the sweep
        }
    }

    @Override
    public List<String> distinctValues(Dimension dim, Window window) {
        String col = dim.column();
        String sql = "SELECT DISTINCT " + col + " AS v FROM trips t "
                + "WHERE t.scheduled_at >= ? AND t.scheduled_at < ? AND " + col
                + " IS NOT NULL ORDER BY v";
        List<String> out = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(sql)) {
            bindWindow(ps, window);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(rs.getString("v"));
                }
            }
        } catch (SQLException e) {
            throw new MetricQueryException("failed to enumerate dimension " + dim, e);
        }
        return out;
    }

    @Override
    public String evidenceSql(Metric metric, Slice slice, Window window) {
        // The literal-substituted form, so a human can paste it into the DuckDB
        // CLI and get the same number. This is what the console shows on expand:
        // "where did this number come from" answered with a query, not a claim.
        String sql = bindSlicePredicate(metric.sql(), slice)
                .replaceFirst("\\?", Long.toString(window.startMs()))
                .replaceFirst("\\?", Long.toString(window.endMs()));
        return slice.dim() == Dimension.NONE
                ? sql
                : sql.replaceFirst("\\?", "'" + slice.value().replace("'", "''") + "'");
    }

    private static String bindSlicePredicate(String sql, Slice slice) {
        String predicate = slice.dim() == Dimension.NONE
                ? "" : "AND " + slice.dim().column() + " = ?";
        return sql.replace("{{SLICE}}", predicate);
    }

    private static int bindWindow(PreparedStatement ps, Window window) throws SQLException {
        ps.setLong(1, window.startMs());
        ps.setLong(2, window.endMs());
        return 3;
    }

    private static void bindSliceValue(PreparedStatement ps, int index, Slice slice)
            throws SQLException {
        if (slice.dim() != Dimension.NONE) {
            ps.setString(index, slice.value());
        }
    }

    private List<String> presentColumns(String table) {
        try (PreparedStatement ps = conn.prepareStatement("SELECT * FROM " + table + " LIMIT 0");
             ResultSet rs = ps.executeQuery()) {
            List<String> cols = new ArrayList<>();
            for (int i = 1; i <= rs.getMetaData().getColumnCount(); i++) {
                cols.add(rs.getMetaData().getColumnName(i));
            }
            return cols;
        } catch (SQLException e) {
            return List.of();
        }
    }

    public static class MetricQueryException extends RuntimeException {
        public MetricQueryException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
```

- [ ] **Step 9: Run the repository tests and read the measured numbers**

Run: `./scripts/mvn.sh -q test -Dtest=DuckDbMetricRepositoryTest`
Expected: PASS, 6 tests. Record the `MEASURED` lines — Task 10 calibrates
against them.

If `theDegradingVendorIsVisiblyWorseThanAPeerInTheFinalWeek` fails, the
regression is not landing in the evaluation window. Check that
`FixtureGenerator.windowEnd()` and `Window.weekEnding` agree on half-open
boundaries before touching the generator.

- [ ] **Step 10: Break-it-to-prove-it**

In `evaluate`, replace the `rs.wasNull()` check with a bare `return
OptionalDouble.of(v)`, rerun. Expected: `anEmptySliceYieldsNoValueRatherThanZero`
FAILS. Restore. Then delete the `{{SLICE}}` replacement so slices are ignored,
rerun. Expected: `theDegradingVendorIsVisiblyWorseThanAPeerInTheFinalWeek` FAILS
because both vendors return the same unsliced number. Restore.

- [ ] **Step 11: Assert the invariant by grep**

`service/src/test/java/com/signaldesk/InvariantTest.java`:

```java
package com.signaldesk;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;

/**
 * The invariant from spec section 1.1, enforced mechanically: the metric registry
 * is the only place outside ingest that holds SQL, and no tool ever runs it.
 */
class InvariantTest {

    private static final List<String> SQL_ALLOWED_PACKAGES =
            List.of("com/signaldesk/registry", "com/signaldesk/ingest");

    @Test
    void noSqlLivesOutsideTheRegistryAndIngestPackages() throws IOException {
        try (Stream<Path> files = Files.walk(Path.of("src/main/java"))) {
            List<Path> offenders = files
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> SQL_ALLOWED_PACKAGES.stream()
                            .noneMatch(allowed -> p.toString().replace('\\', '/').contains(allowed)))
                    .filter(InvariantTest::containsSql)
                    .toList();
            assertThat(offenders)
                    .as("SQL outside registry/ and ingest/ erodes the one decision that matters")
                    .isEmpty();
        }
    }

    @Test
    void noToolExposesRawSqlExecution() throws IOException {
        try (Stream<Path> files = Files.walk(Path.of("src/main/java"))) {
            List<Path> offenders = files
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> p.toString().replace('\\', '/').contains("com/signaldesk/model"))
                    .filter(InvariantTest::containsSql)
                    .toList();
            assertThat(offenders)
                    .as("there is no run_sql tool; that is the difference between this "
                            + "and a text-to-SQL demo")
                    .isEmpty();
        }
    }

    private static boolean containsSql(Path p) {
        try {
            String s = Files.readString(p).toUpperCase();
            return s.contains("SELECT ") || s.contains("CREATE OR REPLACE VIEW");
        } catch (IOException e) {
            return false;
        }
    }
}
```

Run: `./scripts/mvn.sh -q test -Dtest=InvariantTest`
Expected: PASS. This test is the reason the package layout in the File Structure
section is not negotiable.

- [ ] **Step 12: Commit**

```bash
git add service
git commit -m "feat(registry): six governed metric definitions behind a swappable repository"
```

---

### Task 6: Reference resolver — trend, target, peer (~0 h 45)

**Files:**
- Create: `service/src/main/java/com/signaldesk/verdict/Reference.java`
- Create: `service/src/main/java/com/signaldesk/registry/ReferenceResolver.java`
- Test: `service/src/test/java/com/signaldesk/registry/ReferenceResolverTest.java`

**Interfaces:**
- Consumes: `MetricRepository`, `Metric`, `Slice`, `Window`, `ReferenceKind`.
- Produces:
  - `record Reference(ReferenceKind kind, double value, String label)`
  - `ReferenceResolver.resolve(Metric, Slice, Window)` returning `List<Reference>`
    — every reference the metric declares that could actually be computed, in
    declaration order. A reference that cannot be computed is **omitted**, never
    faked.
  - `ReferenceResolver.MIN_PEERS = 3`

TREND is the mean of the metric over the four complete windows preceding the one
under evaluation, averaging the windows that returned a value — so one missing
week degrades the reference rather than voiding it. The evaluated window is
excluded, which is the whole point of the reference and the thing a test must
prove.

- [ ] **Step 1: Write the failing tests**

`service/src/test/java/com/signaldesk/registry/ReferenceResolverTest.java`:

```java
package com.signaldesk.registry;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.verdict.Reference;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.OptionalDouble;
import org.junit.jupiter.api.Test;

class ReferenceResolverTest {

    /** A repository whose answers are dictated per window, so trend maths is exact. */
    static class StubRepository implements MetricRepository {
        final Map<String, Double> byWindowAndSlice = new HashMap<>();
        final Map<Dimension, List<String>> dimensionValues = new HashMap<>();

        static String key(Slice s, Window w) {
            return s.label() + "@" + w.startMs();
        }

        @Override
        public OptionalDouble evaluate(Metric m, Slice s, Window w) {
            Double v = byWindowAndSlice.get(key(s, w));
            return v == null ? OptionalDouble.empty() : OptionalDouble.of(v);
        }

        @Override
        public double coverage(Metric m, Slice s, Window w) {
            return 1.0;
        }

        @Override
        public List<String> distinctValues(Dimension dim, Window w) {
            return dimensionValues.getOrDefault(dim, List.of());
        }

        @Override
        public String evidenceSql(Metric m, Slice s, Window w) {
            return "SELECT 1";
        }
    }

    private final MetricRegistry registry =
            new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));
    private final Window window = Window.weekEnding(7 * Window.WEEK_MS);

    @Test
    void trendIsTheMeanOfTheFourPrecedingWindowsAndExcludesTheEvaluatedOne() {
        StubRepository repo = new StubRepository();
        Slice all = Slice.all();
        repo.byWindowAndSlice.put(StubRepository.key(all, window), 1000.0);   // must be ignored
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(1)), 80.0);
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(2)), 82.0);
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(3)), 84.0);
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(4)), 86.0);

        List<Reference> refs = new ReferenceResolver(repo).resolve(registry.byId("ota"), all, window);

        assertThat(refs).filteredOn(r -> r.kind() == ReferenceKind.TREND)
                .singleElement()
                .satisfies(r -> {
                    assertThat(r.value()).isEqualTo(83.0);   // not 266.4, which includes the window
                    assertThat(r.label()).isEqualTo("4-week average");
                });
    }

    @Test
    void trendAveragesOnlyTheWindowsThatReturnedAValue() {
        StubRepository repo = new StubRepository();
        Slice all = Slice.all();
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(1)), 80.0);
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(3)), 90.0);

        List<Reference> refs = new ReferenceResolver(repo).resolve(registry.byId("ota"), all, window);

        assertThat(refs).filteredOn(r -> r.kind() == ReferenceKind.TREND)
                .singleElement()
                .satisfies(r -> assertThat(r.value()).isEqualTo(85.0));
    }

    @Test
    void trendIsOmittedWhenNoPrecedingWindowHasData() {
        List<Reference> refs = new ReferenceResolver(new StubRepository())
                .resolve(registry.byId("ota"), Slice.all(), window);

        assertThat(refs).noneMatch(r -> r.kind() == ReferenceKind.TREND);
    }

    @Test
    void targetComesFromTheMetricDefinition() {
        List<Reference> refs = new ReferenceResolver(new StubRepository())
                .resolve(registry.byId("sla_breach"), Slice.all(), window);

        assertThat(refs).singleElement().satisfies(r -> {
            assertThat(r.kind()).isEqualTo(ReferenceKind.TARGET);
            assertThat(r.value()).isEqualTo(10.0);
            assertThat(r.label()).isEqualTo("SLA target");
        });
    }

    @Test
    void peerIsTheMedianAcrossTheOtherValuesOfTheSameDimension() {
        StubRepository repo = new StubRepository();
        repo.dimensionValues.put(Dimension.VENDOR, List.of("V01", "V02", "V03", "V04"));
        Slice subject = new Slice(Dimension.VENDOR, "V01");
        repo.byWindowAndSlice.put(StubRepository.key(subject, window), 60.0);         // excluded
        repo.byWindowAndSlice.put(StubRepository.key(new Slice(Dimension.VENDOR, "V02"), window), 88.0);
        repo.byWindowAndSlice.put(StubRepository.key(new Slice(Dimension.VENDOR, "V03"), window), 90.0);
        repo.byWindowAndSlice.put(StubRepository.key(new Slice(Dimension.VENDOR, "V04"), window), 94.0);

        List<Reference> refs = new ReferenceResolver(repo)
                .resolve(registry.byId("vendor_ota"), subject, window);

        assertThat(refs).filteredOn(r -> r.kind() == ReferenceKind.PEER)
                .singleElement()
                .satisfies(r -> {
                    assertThat(r.value()).as("median of 88, 90, 94 — the subject is not its own peer")
                            .isEqualTo(90.0);
                    assertThat(r.label()).isEqualTo("peer median");
                });
    }

    @Test
    void peerIsOmittedRatherThanComputedOnTwoPeers() {
        StubRepository repo = new StubRepository();
        repo.dimensionValues.put(Dimension.VENDOR, List.of("V01", "V02", "V03"));
        Slice subject = new Slice(Dimension.VENDOR, "V01");
        repo.byWindowAndSlice.put(StubRepository.key(new Slice(Dimension.VENDOR, "V02"), window), 88.0);
        repo.byWindowAndSlice.put(StubRepository.key(new Slice(Dimension.VENDOR, "V03"), window), 90.0);

        List<Reference> refs = new ReferenceResolver(repo)
                .resolve(registry.byId("vendor_ota"), subject, window);

        assertThat(refs).as("two peers is not a peer group").noneMatch(r -> r.kind() == ReferenceKind.PEER);
    }

    @Test
    void peerIsOmittedForAnUnslicedFinding() {
        StubRepository repo = new StubRepository();
        repo.dimensionValues.put(Dimension.VENDOR, List.of("V01", "V02", "V03", "V04"));

        List<Reference> refs = new ReferenceResolver(repo)
                .resolve(registry.byId("vendor_ota"), Slice.all(), window);

        assertThat(refs).noneMatch(r -> r.kind() == ReferenceKind.PEER);
    }

    @Test
    void referencesComeBackInDeclarationOrderSoTieBreakingIsStable() {
        StubRepository repo = new StubRepository();
        Slice all = Slice.all();
        repo.byWindowAndSlice.put(StubRepository.key(all, window.shiftedBack(1)), 80.0);

        List<Reference> refs = new ReferenceResolver(repo).resolve(registry.byId("ota"), all, window);

        assertThat(refs).extracting(Reference::kind)
                .containsExactly(ReferenceKind.TREND, ReferenceKind.TARGET);
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=ReferenceResolverTest`
Expected: FAIL — `cannot find symbol: class ReferenceResolver`.

- [ ] **Step 3: Write the Reference record**

`service/src/main/java/com/signaldesk/verdict/Reference.java`:

```java
package com.signaldesk.verdict;

import com.signaldesk.registry.ReferenceKind;

/** What a metric is judged against. A metric without one is just a number. */
public record Reference(ReferenceKind kind, double value, String label) {}
```

- [ ] **Step 4: Write the resolver**

`service/src/main/java/com/signaldesk/registry/ReferenceResolver.java`:

```java
package com.signaldesk.registry;

import com.signaldesk.verdict.Reference;
import java.util.ArrayList;
import java.util.List;
import java.util.OptionalDouble;
import org.springframework.stereotype.Component;

@Component
public class ReferenceResolver {

    /** A median over two values is not a peer comparison. */
    public static final int MIN_PEERS = 3;
    public static final int TREND_WINDOWS = 4;

    private final MetricRepository repo;

    public ReferenceResolver(MetricRepository repo) {
        this.repo = repo;
    }

    /** Every declared reference that could actually be computed, in declaration order. */
    public List<Reference> resolve(Metric metric, Slice slice, Window window) {
        List<Reference> out = new ArrayList<>();
        for (ReferenceKind kind : metric.refs()) {
            switch (kind) {
                case TREND -> trend(metric, slice, window).ifPresent(out::add);
                case TARGET -> out.add(new Reference(ReferenceKind.TARGET, metric.target(), "SLA target"));
                case PEER -> peer(metric, slice, window).ifPresent(out::add);
            }
        }
        return List.copyOf(out);
    }

    private java.util.Optional<Reference> trend(Metric metric, Slice slice, Window window) {
        double sum = 0;
        int n = 0;
        for (int back = 1; back <= TREND_WINDOWS; back++) {
            OptionalDouble v = repo.evaluate(metric, slice, window.shiftedBack(back));
            if (v.isPresent()) {
                sum += v.getAsDouble();
                n++;
            }
        }
        return n == 0
                ? java.util.Optional.empty()
                : java.util.Optional.of(new Reference(ReferenceKind.TREND, sum / n, "4-week average"));
    }

    private java.util.Optional<Reference> peer(Metric metric, Slice slice, Window window) {
        if (slice.dim() == Dimension.NONE) {
            return java.util.Optional.empty();
        }
        List<Double> peers = new ArrayList<>();
        for (String value : repo.distinctValues(slice.dim(), window)) {
            if (value.equals(slice.value())) {
                continue;                       // the subject is not its own peer
            }
            repo.evaluate(metric, new Slice(slice.dim(), value), window)
                    .ifPresent(peers::add);
        }
        if (peers.size() < MIN_PEERS) {
            return java.util.Optional.empty();
        }
        peers.sort(Double::compareTo);
        int mid = peers.size() / 2;
        double median = peers.size() % 2 == 1
                ? peers.get(mid)
                : (peers.get(mid - 1) + peers.get(mid)) / 2.0;
        return java.util.Optional.of(new Reference(ReferenceKind.PEER, median, "peer median"));
    }
}
```

- [ ] **Step 5: Run the tests**

Run: `./scripts/mvn.sh -q test -Dtest=ReferenceResolverTest`
Expected: PASS, 8 tests.

- [ ] **Step 6: Break-it-to-prove-it, twice**

Change `for (int back = 1; ...)` to `for (int back = 0; ...)` so the evaluated
window is included, rerun. Expected:
`trendIsTheMeanOfTheFourPrecedingWindowsAndExcludesTheEvaluatedOne` FAILS with
the value 266.4 rather than 83.0. Restore.

Change `MIN_PEERS` to 2, rerun. Expected: `peerIsOmittedRatherThanComputedOnTwoPeers`
FAILS. Restore.

Remove the `value.equals(slice.value())` skip, rerun. Expected: the peer-median
test FAILS, because the subject's own 60.0 drags the median to 89.0. Restore.

- [ ] **Step 7: Commit**

```bash
git add service
git commit -m "feat(registry): trend, target and peer reference resolution, omitting what it cannot compute"
```

---

### Task 7: Verdict engine — four tiers, and a gap whose sign cannot lie (~0 h 45)

**Files:**
- Create: `service/src/main/java/com/signaldesk/verdict/Tier.java`, `Cause.java`, `Finding.java`, `FindingId.java`, `DeltaRule.java`, `VerdictEngine.java`
- Test: `service/src/test/java/com/signaldesk/verdict/DeltaRuleTest.java`
- Test: `service/src/test/java/com/signaldesk/verdict/VerdictEngineTest.java`

**Interfaces:**
- Consumes: `MetricRepository`, `ReferenceResolver`, `Reference`, `Metric`, `Slice`, `Window`, `GapRegister`.
- Produces:
  - `enum Tier { PASS, WATCH, CONCERN, BREACH }` — ordinal, compared with `compareTo`, **never summed**
  - `enum Cause { ON_REFERENCE, BELOW_TARGET, TREND_REGRESSION, PEER_LAGGARD, LOW_CONFIDENCE, DATA_GAP }`
  - `enum Audience { TRANSPORT_MANAGER, FACILITIES_HEAD, LINE_MANAGER }`
  - `record Finding(String id, String metricId, Slice slice, Window window, double observed, List<Reference> refs, Tier tier, Cause cause, double gap, double confidence, Set<Audience> audiences, String evidenceSql)`
  - `DeltaRule.delta(double observed, double reference, Direction better)`,
    `DeltaRule.tierFor(double delta, boolean hardTarget)`,
    `DeltaRule.PASS_MAX = 0.02`, `WATCH_MAX = 0.05`, `CONCERN_MAX = 0.15`
  - `VerdictEngine.evaluate(Metric, Slice, Window)` returning `Optional<Finding>`

`Cause.ON_REFERENCE` is an addition to the spec's §6.2 list. A `PASS` has to carry
*some* cause, and labelling a passing metric `BELOW_TARGET` because the target was
the reference that happened to be worst is a sentence nobody should read.

**Reminder of resolved deviation 1:** `gap = delta * reference`, so **positive
always means worse**, for both metric directions. §6.2's "observed − reference"
wording is superseded.

- [ ] **Step 1: Write the failing delta tests**

`service/src/test/java/com/signaldesk/verdict/DeltaRuleTest.java`:

```java
package com.signaldesk.verdict;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.registry.Direction;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class DeltaRuleTest {

    @Test
    void oneFormulaCoversBothDirections() {
        // 78 against a target of 90, higher-is-better: 13.3% worse
        assertThat(DeltaRule.delta(78, 90, Direction.HIGHER)).isCloseTo(0.1333, within(0.0001));
        // 25 against a target of 10, lower-is-better: 150% worse
        assertThat(DeltaRule.delta(25, 10, Direction.LOWER)).isCloseTo(1.50, within(0.0001));
        // and better-than-reference is negative in both directions
        assertThat(DeltaRule.delta(95, 90, Direction.HIGHER)).isNegative();
        assertThat(DeltaRule.delta(5, 10, Direction.LOWER)).isNegative();
    }

    @ParameterizedTest
    @CsvSource({
        "-0.50, PASS",
        " 0.00, PASS",
        " 0.02, PASS",
        " 0.021, WATCH",
        " 0.05, WATCH",
        " 0.051, CONCERN",
        " 0.15, CONCERN",
        " 0.151, BREACH",
        " 2.00, BREACH",
    })
    void allFourTiersAreReachableAndTheBoundariesAreInclusiveUpwards(double delta, Tier expected) {
        assertThat(DeltaRule.tierFor(delta, false)).isEqualTo(expected);
    }

    @Test
    void aHardTargetBreachesOnAnyShortfallAtAll() {
        // night_compliance's target of 100 is a compliance floor, not an aspiration
        assertThat(DeltaRule.tierFor(0.001, true)).isEqualTo(Tier.BREACH);
        assertThat(DeltaRule.tierFor(0.0, true)).isEqualTo(Tier.PASS);
        assertThat(DeltaRule.tierFor(-0.1, true)).isEqualTo(Tier.PASS);
    }

    @Test
    void aZeroReferenceSaturatesRatherThanDividingByZero() {
        assertThat(DeltaRule.delta(0, 0, Direction.LOWER)).isEqualTo(0.0);
        assertThat(DeltaRule.delta(7, 0, Direction.LOWER)).isEqualTo(1.0);
        assertThat(DeltaRule.delta(7, 0, Direction.HIGHER)).isEqualTo(-1.0);
        assertThat(DeltaRule.delta(0, 0, Direction.HIGHER)).isEqualTo(0.0);
    }

    @Test
    void gapSignAgreesWithTierForBothDirections() {
        // A sign-flipped gap produces a confidently wrong sentence, so this is asserted
        // rather than trusted. Two directions, because one would pass under a
        // hardcoded sign.
        double higherGap = DeltaRule.delta(78, 90, Direction.HIGHER) * 90;
        double lowerGap = DeltaRule.delta(25, 10, Direction.LOWER) * 10;
        assertThat(higherGap).as("shortfall on a higher-is-better metric").isPositive();
        assertThat(lowerGap).as("excess on a lower-is-better metric").isPositive();

        double higherPass = DeltaRule.delta(95, 90, Direction.HIGHER) * 90;
        double lowerPass = DeltaRule.delta(5, 10, Direction.LOWER) * 10;
        assertThat(higherPass).isNegative();
        assertThat(lowerPass).isNegative();
    }

    private static org.assertj.core.data.Offset<Double> within(double d) {
        return org.assertj.core.data.Offset.offset(d);
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=DeltaRuleTest`
Expected: FAIL — `cannot find symbol: class DeltaRule`.

- [ ] **Step 3: Write the tier and cause enums**

`Tier.java`:

```java
package com.signaldesk.verdict;

/**
 * Ordered, compared ordinally, NEVER summed into a score. Summing would let three
 * mild issues outrank one genuine breach.
 *
 * CONCERN exists so "a vendor is degrading against its own trend" can outrank
 * "a metric is slightly off target" without either becoming a breach.
 */
public enum Tier { PASS, WATCH, CONCERN, BREACH }
```

`Cause.java`:

```java
package com.signaldesk.verdict;

public enum Cause {
    /** Not an issue: the observed value is at or better than every reference. */
    ON_REFERENCE,
    BELOW_TARGET,
    TREND_REGRESSION,
    PEER_LAGGARD,
    LOW_CONFIDENCE,
    DATA_GAP
}
```

`Audience.java`:

```java
package com.signaldesk.verdict;

public enum Audience { TRANSPORT_MANAGER, FACILITIES_HEAD, LINE_MANAGER }
```

- [ ] **Step 4: Write the delta rule**

`DeltaRule.java`:

```java
package com.signaldesk.verdict;

import com.signaldesk.registry.Direction;
import com.signaldesk.registry.ReferenceKind;

/**
 * A pure function of its inputs. No I/O, no clock, no model.
 *
 * delta is the shortfall against a reference as a fraction of that reference,
 * signed so POSITIVE ALWAYS MEANS WORSE whichever way the metric points. Defining
 * it this way removes the sign confusion that a lower-is-better metric like
 * sla_breach otherwise invites: one formula covers both directions, and
 * Finding.gap is delta x reference, so its sign agrees with the tier by
 * construction rather than by care.
 *
 * MEASURED TIER DISTRIBUTION: see the comment in VerdictEngineTest, filled in by
 * Task 10. These bands are provisional until then.
 */
public final class DeltaRule {

    public static final double PASS_MAX = 0.02;
    public static final double WATCH_MAX = 0.05;
    public static final double CONCERN_MAX = 0.15;
    /** Below this, no tier above WATCH may be emitted. */
    public static final double MIN_TRUSTED_CONFIDENCE = 0.5;

    private DeltaRule() {}

    public static double delta(double observed, double reference, Direction better) {
        if (reference == 0.0) {
            // Saturate rather than divide by zero. A zero reference means any
            // non-zero observation is wholly off it, in whichever direction.
            if (observed == 0.0) {
                return 0.0;
            }
            return better == Direction.LOWER ? 1.0 : -1.0;
        }
        double shortfall = better == Direction.HIGHER ? reference - observed : observed - reference;
        return shortfall / Math.abs(reference);
    }

    public static Tier tierFor(double delta, boolean hardTarget) {
        if (hardTarget) {
            return delta > 0.0 ? Tier.BREACH : Tier.PASS;
        }
        if (delta <= PASS_MAX) {
            return Tier.PASS;
        }
        if (delta <= WATCH_MAX) {
            return Tier.WATCH;
        }
        if (delta <= CONCERN_MAX) {
            return Tier.CONCERN;
        }
        return Tier.BREACH;
    }

    public static Cause causeFor(ReferenceKind kind) {
        return switch (kind) {
            case TARGET -> Cause.BELOW_TARGET;
            case TREND -> Cause.TREND_REGRESSION;
            case PEER -> Cause.PEER_LAGGARD;
        };
    }

    /** Low confidence caps severity; it never improves it. */
    public static Tier capForConfidence(Tier tier, double confidence) {
        if (confidence >= MIN_TRUSTED_CONFIDENCE) {
            return tier;
        }
        return tier.compareTo(Tier.WATCH) > 0 ? Tier.WATCH : tier;
    }
}
```

- [ ] **Step 5: Run the delta tests**

Run: `./scripts/mvn.sh -q test -Dtest=DeltaRuleTest`
Expected: PASS, 5 tests (the parameterized one contributing 9 cases).

- [ ] **Step 6: Write the failing engine tests**

`service/src/test/java/com/signaldesk/verdict/VerdictEngineTest.java`:

```java
package com.signaldesk.verdict;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.ingest.Feed;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.Metric;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.MetricRepository;
import com.signaldesk.registry.ReferenceKind;
import com.signaldesk.registry.ReferenceResolver;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalDouble;
import org.junit.jupiter.api.Test;

class VerdictEngineTest {

    static class StubRepository implements MetricRepository {
        final Map<String, Double> values = new HashMap<>();
        double coverage = 1.0;
        List<String> vendors = List.of();

        static String key(Slice s, Window w) {
            return s.label() + "@" + w.startMs();
        }

        @Override public OptionalDouble evaluate(Metric m, Slice s, Window w) {
            Double v = values.get(key(s, w));
            return v == null ? OptionalDouble.empty() : OptionalDouble.of(v);
        }
        @Override public double coverage(Metric m, Slice s, Window w) { return coverage; }
        @Override public List<String> distinctValues(Dimension d, Window w) { return vendors; }
        @Override public String evidenceSql(Metric m, Slice s, Window w) {
            return "SELECT /* " + m.id() + " */ 1";
        }
    }

    private final MetricRegistry registry =
            new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));
    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);
    private final StubRepository repo = new StubRepository();

    private VerdictEngine engine(double feedConfidence) {
        return new VerdictEngine(repo, new ReferenceResolver(repo), feed -> feedConfidence);
    }

    @Test
    void takesTheWorstTierAcrossEveryReferenceAndKeepsThemAll() {
        Metric ota = registry.byId("ota");                 // TREND then TARGET, target 90
        repo.values.put(StubRepository.key(Slice.all(), window), 78.0);
        repo.values.put(StubRepository.key(Slice.all(), window.shiftedBack(1)), 79.0);

        Finding f = engine(1.0).evaluate(ota, Slice.all(), window).orElseThrow();

        assertThat(f.refs()).as("every reference evaluated, not just the worst").hasSize(2);
        assertThat(f.tier()).as("13.3% below target beats 1.3% below trend").isEqualTo(Tier.CONCERN);
        assertThat(f.cause()).isEqualTo(Cause.BELOW_TARGET);
        assertThat(f.gap()).isCloseTo(12.0, org.assertj.core.data.Offset.offset(0.01));
    }

    @Test
    void aPassingMetricCarriesNoAccusatoryCause() {
        repo.values.put(StubRepository.key(Slice.all(), window), 95.0);
        repo.values.put(StubRepository.key(Slice.all(), window.shiftedBack(1)), 94.0);

        Finding f = engine(1.0).evaluate(registry.byId("ota"), Slice.all(), window).orElseThrow();

        assertThat(f.tier()).isEqualTo(Tier.PASS);
        assertThat(f.cause()).isEqualTo(Cause.ON_REFERENCE);
        assertThat(f.gap()).as("a PASS may never carry a gap indicating a breach").isNegative();
    }

    @Test
    void lowConfidenceCapsAtWatchAndSaysWhy() {
        repo.values.put(StubRepository.key(Slice.all(), window), 40.0);   // would BREACH

        Finding f = engine(0.4).evaluate(registry.byId("sla_breach"), Slice.all(), window).orElseThrow();

        assertThat(f.tier()).isEqualTo(Tier.WATCH);
        assertThat(f.cause()).isEqualTo(Cause.LOW_CONFIDENCE);
        assertThat(f.confidence()).isLessThan(DeltaRule.MIN_TRUSTED_CONFIDENCE);
    }

    @Test
    void lowConfidenceDoesNotPromoteAPassToAWatch() {
        repo.values.put(StubRepository.key(Slice.all(), window), 2.0);    // well inside target

        Finding f = engine(0.4).evaluate(registry.byId("sla_breach"), Slice.all(), window).orElseThrow();

        assertThat(f.tier()).as("the cap lowers severity; it never raises it").isEqualTo(Tier.PASS);
    }

    @Test
    void aMissingColumnDegradesConfidenceThroughCoverage() {
        repo.values.put(StubRepository.key(Slice.all(), window), 40.0);
        repo.coverage = 0.0;                                              // column absent entirely

        Finding f = engine(1.0).evaluate(registry.byId("sla_breach"), Slice.all(), window).orElseThrow();

        assertThat(f.confidence()).isEqualTo(0.0);
        assertThat(f.tier()).isEqualTo(Tier.WATCH);
        assertThat(f.cause()).isEqualTo(Cause.LOW_CONFIDENCE);
    }

    @Test
    void anUnmeasurableOverallMetricIsAFindingNotSilence() {
        Optional<Finding> f = engine(1.0).evaluate(registry.byId("ota"), Slice.all(), window);

        assertThat(f).isPresent();
        assertThat(f.get().cause()).isEqualTo(Cause.DATA_GAP);
        assertThat(f.get().tier()).isEqualTo(Tier.WATCH);
    }

    @Test
    void anEmptySliceIsSkippedRatherThanReportedAsAGap() {
        repo.vendors = List.of("V01", "V02", "V03", "V04");

        Optional<Finding> f = engine(1.0)
                .evaluate(registry.byId("vendor_ota"), new Slice(Dimension.VENDOR, "V09"), window);

        assertThat(f).as("a vendor that did not operate this week is not news").isEmpty();
    }

    @Test
    void aMetricWithNoComputableReferenceEmitsNothing() {
        // vendor_ota declares TREND and PEER only. With no prior windows and no
        // peers, there is nothing to contextualise against, and an uncontextualised
        // number is exactly what this product refuses to ship.
        repo.values.put(StubRepository.key(new Slice(Dimension.VENDOR, "V01"), window), 61.0);

        Optional<Finding> f = engine(1.0)
                .evaluate(registry.byId("vendor_ota"), new Slice(Dimension.VENDOR, "V01"), window);

        assertThat(f).isEmpty();
    }

    @Test
    void findingIdIsStableAcrossRunsAndDistinctAcrossSlices() {
        repo.values.put(StubRepository.key(Slice.all(), window), 78.0);
        repo.values.put(StubRepository.key(new Slice(Dimension.VENDOR, "V01"), window), 78.0);
        repo.vendors = List.of("V01", "V02", "V03", "V04");
        VerdictEngine e = engine(1.0);

        String a = e.evaluate(registry.byId("ota"), Slice.all(), window).orElseThrow().id();
        String b = e.evaluate(registry.byId("ota"), Slice.all(), window).orElseThrow().id();
        String c = e.evaluate(registry.byId("ota"), new Slice(Dimension.VENDOR, "V01"), window)
                .orElseThrow().id();

        assertThat(a).isEqualTo(b);
        assertThat(a).isNotEqualTo(c);
    }

    @Test
    void evidenceSqlIsCarriedOnEveryFinding() {
        repo.values.put(StubRepository.key(Slice.all(), window), 78.0);

        Finding f = engine(1.0).evaluate(registry.byId("ota"), Slice.all(), window).orElseThrow();

        assertThat(f.evidenceSql()).contains("ota");
    }
}
```

- [ ] **Step 7: Write FindingId and Finding**

`FindingId.java`:

```java
package com.signaldesk.verdict;

import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Stable across runs, so a finding can be re-opened by URL and re-explained. */
public final class FindingId {

    private FindingId() {}

    public static String of(String metricId, Slice slice, Window window) {
        String material = String.join("|", metricId, slice.dim().name(),
                slice.value() == null ? "" : slice.value(),
                Long.toString(window.startMs()), Long.toString(window.endMs()));
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(material.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash).substring(0, 12);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }
}
```

`Finding.java`:

```java
package com.signaldesk.verdict;

import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import java.util.List;
import java.util.Set;

/**
 * The unit of everything downstream: the console renders it, the narrative is
 * written from it, delivery routes on it.
 *
 * gap is delta x reference, so POSITIVE ALWAYS MEANS WORSE and the sign agrees
 * with the tier by construction. (Spec section 6.2's "observed - reference"
 * wording is superseded by section 6.3; see the plan's deviation 1.)
 *
 * audiences is a Set, not one value: a BREACH assigns two, and a single field
 * would silently drop a recipient.
 *
 * evidenceSql is not decoration. It is the answer to "where did this number come
 * from", as a query the reader can run, rather than a claim.
 */
public record Finding(
        String id,
        String metricId,
        Slice slice,
        Window window,
        double observed,
        List<Reference> refs,
        Tier tier,
        Cause cause,
        double gap,
        double confidence,
        Set<Audience> audiences,
        String evidenceSql) {

    public Finding {
        refs = List.copyOf(refs);
        audiences = Set.copyOf(audiences);
        if (tier == Tier.PASS && gap > 0) {
            throw new IllegalArgumentException(
                    "finding " + id + " is a PASS carrying a positive (worse-than-reference) gap");
        }
    }

    public boolean mustDiscloseConfidence() {
        return confidence < 0.9;
    }
}
```

The constructor check is the same property `gapSignAgreesWithTierForBothDirections`
asserts, enforced at runtime as well. A sign-flipped gap should be impossible to
construct, not merely unlikely.

- [ ] **Step 8: Write the verdict engine**

`VerdictEngine.java`:

```java
package com.signaldesk.verdict;

import com.signaldesk.ingest.Feed;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.Metric;
import com.signaldesk.registry.MetricRepository;
import com.signaldesk.registry.ReferenceResolver;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import java.util.List;
import java.util.Optional;
import java.util.OptionalDouble;
import java.util.function.ToDoubleFunction;
import org.springframework.stereotype.Component;

@Component
public class VerdictEngine {

    private final MetricRepository repo;
    private final ReferenceResolver resolver;
    private final ToDoubleFunction<Feed> feedConfidence;

    public VerdictEngine(MetricRepository repo, ReferenceResolver resolver,
                         ToDoubleFunction<Feed> feedConfidence) {
        this.repo = repo;
        this.resolver = resolver;
        this.feedConfidence = feedConfidence;
    }

    public Optional<Finding> evaluate(Metric metric, Slice slice, Window window) {
        OptionalDouble observed = repo.evaluate(metric, slice, window);
        double confidence = feedConfidence.applyAsDouble(metric.source())
                * repo.coverage(metric, slice, window);

        if (observed.isEmpty()) {
            // An unmeasurable OVERALL metric is a finding: the agent is loud about
            // what it cannot read. An unmeasurable SLICE is not — a vendor that did
            // not operate this week is not news.
            return slice.dim() == Dimension.NONE
                    ? Optional.of(dataGap(metric, slice, window, confidence))
                    : Optional.empty();
        }

        List<Reference> refs = resolver.resolve(metric, slice, window);
        if (refs.isEmpty()) {
            // An uncontextualised number is what this product exists to refuse.
            return Optional.empty();
        }

        Tier worst = Tier.PASS;
        Reference firing = refs.get(0);
        double worstDelta = Double.NEGATIVE_INFINITY;
        for (Reference ref : refs) {
            double delta = DeltaRule.delta(observed.getAsDouble(), ref.value(), metric.better());
            boolean hard = metric.hardTarget() && ref.kind() == com.signaldesk.registry.ReferenceKind.TARGET;
            Tier tier = DeltaRule.tierFor(delta, hard);
            // Strictly greater, so ties keep the earlier-declared reference.
            if (tier.compareTo(worst) > 0 || (tier == worst && delta > worstDelta)) {
                worst = tier;
                firing = ref;
                worstDelta = delta;
            }
        }

        Tier capped = DeltaRule.capForConfidence(worst, confidence);
        Cause cause = capped != worst ? Cause.LOW_CONFIDENCE
                : capped == Tier.PASS ? Cause.ON_REFERENCE
                : DeltaRule.causeFor(firing.kind());
        double gap = worstDelta * firing.value();

        return Optional.of(new Finding(
                FindingId.of(metric.id(), slice, window),
                metric.id(), slice, window, observed.getAsDouble(), refs,
                capped, cause, gap, confidence,
                AudienceAssigner.forFinding(metric.id(), slice, capped),
                repo.evidenceSql(metric, slice, window)));
    }

    private Finding dataGap(Metric metric, Slice slice, Window window, double confidence) {
        return new Finding(
                FindingId.of(metric.id(), slice, window),
                metric.id(), slice, window, 0.0, List.of(),
                Tier.WATCH, Cause.DATA_GAP, 0.0, confidence,
                AudienceAssigner.forFinding(metric.id(), slice, Tier.WATCH),
                repo.evidenceSql(metric, slice, window));
    }
}
```

`VerdictEngine` takes `ToDoubleFunction<Feed>` rather than `GapRegister` so the
engine stays free of ingest concerns and is trivially stubbed. Wire the real one
with a small `@Bean` in Task 9.

- [ ] **Step 9: Run the engine tests**

Run: `./scripts/mvn.sh -q test -Dtest=VerdictEngineTest`
Expected: FAIL on `AudienceAssigner` not existing — that is Task 8. Write a
temporary stub returning `Set.of(Audience.TRANSPORT_MANAGER)` to get the suite
green, and remove it in Task 8 Step 3.

- [ ] **Step 10: Break-it-to-prove-it, three times**

Change `tier.compareTo(worst) > 0` to `< 0`, rerun. Expected:
`takesTheWorstTierAcrossEveryReferenceAndKeepsThemAll` FAILS. Restore.

Delete the `capForConfidence` call, rerun. Expected: `lowConfidenceCapsAtWatchAndSaysWhy`
and `aMissingColumnDegradesConfidenceThroughCoverage` FAIL. Restore.

Change `refs.isEmpty()` to return a finding anyway, rerun. Expected:
`aMetricWithNoComputableReferenceEmitsNothing` FAILS. Restore.

- [ ] **Step 11: Commit**

```bash
git add service
git commit -m "feat(verdict): four-tier rules with a gap whose sign cannot disagree with its tier"
```

---

### Task 8: Ranking and audience assignment (~0 h 20)

**Files:**
- Create: `service/src/main/java/com/signaldesk/verdict/Ranker.java`
- Create: `service/src/main/java/com/signaldesk/verdict/AudienceAssigner.java`
- Test: `service/src/test/java/com/signaldesk/verdict/RankerTest.java`
- Test: `service/src/test/java/com/signaldesk/verdict/AudienceAssignerTest.java`
- Modify: `service/src/main/java/com/signaldesk/verdict/VerdictEngine.java` (remove the Task 7 stub)

**Interfaces:**
- Consumes: `Finding`, `Tier`, `Slice`, `Dimension`.
- Produces:
  - `Ranker.rank(List<Finding>)` returning a new sorted list
  - `Ranker.COMPARATOR`
  - `AudienceAssigner.forFinding(String metricId, Slice slice, Tier tier)` returning `Set<Audience>`

- [ ] **Step 1: Write the failing ranking test**

`service/src/test/java/com/signaldesk/verdict/RankerTest.java`:

```java
package com.signaldesk.verdict;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import java.util.List;
import java.util.Set;
import java.util.stream.IntStream;
import org.junit.jupiter.api.Test;

class RankerTest {

    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);

    private Finding finding(String id, Tier tier, double gap, double confidence) {
        return new Finding(id, "ota", Slice.all(), window, 78.0, List.of(),
                tier, tier == Tier.PASS ? Cause.ON_REFERENCE : Cause.BELOW_TARGET,
                tier == Tier.PASS ? -1.0 : gap, confidence,
                Set.of(Audience.TRANSPORT_MANAGER), "SELECT 1");
    }

    @Test
    void oneBreachOutranksAnyNumberOfWatches() {
        // The no-summing property. Twenty mild issues must not outrank one genuine
        // breach, which is what a weighted score would do.
        List<Finding> many = IntStream.range(0, 20)
                .mapToObj(i -> finding("w" + i, Tier.WATCH, 40.0, 1.0))
                .collect(java.util.stream.Collectors.toCollection(java.util.ArrayList::new));
        many.add(finding("b1", Tier.BREACH, 0.5, 1.0));

        List<Finding> ranked = Ranker.rank(many);

        assertThat(ranked.get(0).id()).isEqualTo("b1");
    }

    @Test
    void withinATierTheLargerAbsoluteGapRanksFirst() {
        List<Finding> ranked = Ranker.rank(List.of(
                finding("small", Tier.CONCERN, 3.0, 1.0),
                finding("large", Tier.CONCERN, 19.0, 1.0),
                finding("mid", Tier.CONCERN, 8.0, 1.0)));

        assertThat(ranked).extracting(Finding::id).containsExactly("large", "mid", "small");
    }

    @Test
    void withinATierAndGapTheMoreConfidentFindingRanksFirst() {
        List<Finding> ranked = Ranker.rank(List.of(
                finding("unsure", Tier.CONCERN, 8.0, 0.6),
                finding("sure", Tier.CONCERN, 8.0, 0.95)));

        assertThat(ranked).extracting(Finding::id).containsExactly("sure", "unsure");
    }

    @Test
    void rankingDoesNotMutateTheInput() {
        List<Finding> input = new java.util.ArrayList<>(List.of(
                finding("a", Tier.WATCH, 1.0, 1.0),
                finding("b", Tier.BREACH, 1.0, 1.0)));

        Ranker.rank(input);

        assertThat(input).extracting(Finding::id).containsExactly("a", "b");
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=RankerTest`
Expected: FAIL — `cannot find symbol: class Ranker`.

- [ ] **Step 3: Write the ranker and the audience assigner**

`Ranker.java`:

```java
package com.signaldesk.verdict;

import java.util.Comparator;
import java.util.List;

public final class Ranker {

    /**
     * Tier first and ordinally: no arithmetic combines the three keys, so no number
     * of WATCHes can ever add up to a BREACH.
     */
    public static final Comparator<Finding> COMPARATOR =
            Comparator.comparing(Finding::tier, Comparator.reverseOrder())
                    .thenComparing(f -> Math.abs(f.gap()), Comparator.reverseOrder())
                    .thenComparing(Finding::confidence, Comparator.reverseOrder())
                    .thenComparing(Finding::id);

    private Ranker() {}

    public static List<Finding> rank(List<Finding> findings) {
        return findings.stream().sorted(COMPARATOR).toList();
    }
}
```

The trailing `.thenComparing(Finding::id)` is not decoration: without a total
order, the sweep determinism test in Task 9 fails intermittently on ties, which
is the worst kind of failure to debug at hour eleven.

`AudienceAssigner.java`:

```java
package com.signaldesk.verdict;

import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.Slice;
import java.util.EnumSet;
import java.util.Set;

/** Assigned by rule, not by the model. */
public final class AudienceAssigner {

    private AudienceAssigner() {}

    public static Set<Audience> forFinding(String metricId, Slice slice, Tier tier) {
        EnumSet<Audience> out = EnumSet.noneOf(Audience.class);

        if (tier == Tier.BREACH) {
            out.add(Audience.FACILITIES_HEAD);
            out.add(Audience.TRANSPORT_MANAGER);
        }
        switch (metricId) {
            case "vendor_ota", "cost_per_trip" -> out.add(Audience.FACILITIES_HEAD);
            case "ota", "sla_breach", "night_compliance" -> out.add(Audience.TRANSPORT_MANAGER);
            default -> out.add(Audience.TRANSPORT_MANAGER);
        }
        if (slice.dim() == Dimension.SHIFT) {
            out.add(Audience.LINE_MANAGER);
        }
        return Set.copyOf(out);
    }
}
```

- [ ] **Step 4: Write the audience tests**

`service/src/test/java/com/signaldesk/verdict/AudienceAssignerTest.java`:

```java
package com.signaldesk.verdict;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.Slice;
import org.junit.jupiter.api.Test;

class AudienceAssignerTest {

    @Test
    void aBreachReachesBothTheFacilitiesHeadAndTheTransportManager() {
        assertThat(AudienceAssigner.forFinding("ota", Slice.all(), Tier.BREACH))
                .containsExactlyInAnyOrder(Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER);
    }

    @Test
    void vendorAndCostMetricsGoToTheFacilitiesHead() {
        assertThat(AudienceAssigner.forFinding("vendor_ota", Slice.all(), Tier.CONCERN))
                .containsExactly(Audience.FACILITIES_HEAD);
        assertThat(AudienceAssigner.forFinding("cost_per_trip", Slice.all(), Tier.CONCERN))
                .containsExactly(Audience.FACILITIES_HEAD);
    }

    @Test
    void operationalMetricsGoToTheTransportManager() {
        assertThat(AudienceAssigner.forFinding("sla_breach", Slice.all(), Tier.WATCH))
                .containsExactly(Audience.TRANSPORT_MANAGER);
        assertThat(AudienceAssigner.forFinding("night_compliance", Slice.all(), Tier.WATCH))
                .containsExactly(Audience.TRANSPORT_MANAGER);
    }

    @Test
    void anythingSlicedByShiftAlsoReachesTheLineManager() {
        assertThat(AudienceAssigner.forFinding("ota", new Slice(Dimension.SHIFT, "S3"), Tier.WATCH))
                .contains(Audience.LINE_MANAGER);
        assertThat(AudienceAssigner.forFinding("ota", new Slice(Dimension.VENDOR, "V07"), Tier.WATCH))
                .doesNotContain(Audience.LINE_MANAGER);
    }

    @Test
    void aBreachSlicedByShiftReachesAllThree() {
        // The reason audiences is a Set: three recipients from three independent
        // rules, and a single field would silently drop two.
        assertThat(AudienceAssigner.forFinding("vendor_ota", new Slice(Dimension.SHIFT, "S3"), Tier.BREACH))
                .containsExactlyInAnyOrder(Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER,
                        Audience.LINE_MANAGER);
    }
}
```

- [ ] **Step 5: Remove the Task 7 stub and run everything**

Delete the temporary `AudienceAssigner` stub from Task 7 Step 9.

Run: `./scripts/mvn.sh -q test`
Expected: PASS, whole suite.

- [ ] **Step 6: Break-it-to-prove-it**

In `COMPARATOR`, move `thenComparing(f -> Math.abs(f.gap()))` ahead of the tier
comparison, rerun. Expected: `oneBreachOutranksAnyNumberOfWatches` FAILS — the
WATCH with gap 40 wins. Restore. This is the no-summing property demonstrated
rather than asserted.

- [ ] **Step 7: Commit**

```bash
git add service
git commit -m "feat(verdict): ordinal ranking and rule-assigned audiences"
```

---

### Task 9: The sense step — a sweep that fires with no prompt (~0 h 30)

**Files:**
- Create: `service/src/main/java/com/signaldesk/agent/SweepRun.java`, `FindingStore.java`, `Sweep.java`, `SweepScheduler.java`, `ClockConfig.java`, `VerdictConfig.java`
- Create: `service/src/main/java/com/signaldesk/api/SweepController.java`
- Test: `service/src/test/java/com/signaldesk/agent/SweepTest.java`
- Modify: `service/src/main/resources/application.yaml`

**Interfaces:**
- Consumes: `MetricRegistry`, `MetricRepository`, `ReferenceResolver`, `VerdictEngine`, `Ranker`, `GapRegister`, `java.time.Clock`.
- Produces:
  - `record SweepRun(String runId, Window window, List<Finding> findings, Map<Feed, FeedHealth> feedHealth, long sweptAtMs)`
  - `Sweep.run()` returning `SweepRun`
  - `FindingStore.put(SweepRun)`, `get(String runId)`, `latest()`, `finding(String findingId)`
  - `POST /api/sweep` returning `{ "runId": "...", "findingCount": n }`

**This is the step that satisfies "agentic — senses, reasons and acts".** No
prompt is involved. The `@Scheduled` sweep is the real loop; the manual trigger
exists so a judge can *watch* it fire, not because the loop needs asking. Say
that on stage in those words.

The demo drives a **simulated clock**, so the same run always produces the same
findings.

- [ ] **Step 1: Write the failing sweep tests**

`service/src/test/java/com/signaldesk/agent/SweepTest.java`:

```java
package com.signaldesk.agent;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.signaldesk.fixture.FixtureGenerator;
import com.signaldesk.ingest.DuckDbLoader;
import com.signaldesk.ingest.GapRegister;
import com.signaldesk.registry.DuckDbMetricRepository;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.ReferenceResolver;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Tier;
import com.signaldesk.verdict.VerdictEngine;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SweepTest {

    private Connection conn;
    private Sweep sweep;

    @BeforeEach
    void wireAgainstTheCommittedFixture() throws Exception {
        Path dir = Path.of("..", "data", "fixture");
        assumeTrue(Files.isDirectory(dir), "committed fixture not present");

        conn = DriverManager.getConnection("jdbc:duckdb:");
        DuckDbLoader loader = new DuckDbLoader(conn,
                feed -> dir.resolve(feed.fileName()).toAbsolutePath().toString());
        loader.loadAll();

        GapRegister gaps = new GapRegister(conn, loader);
        gaps.assess();
        DuckDbMetricRepository repo = new DuckDbMetricRepository(conn);
        MetricRegistry registry = new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));
        VerdictEngine engine = new VerdictEngine(repo, new ReferenceResolver(repo), gaps::confidenceFor);

        Clock simulated = Clock.fixed(
                Instant.ofEpochMilli(FixtureGenerator.windowEnd()), ZoneOffset.UTC);
        sweep = new Sweep(registry, repo, engine, gaps, simulated, 7);
    }

    @AfterEach
    void close() throws Exception {
        conn.close();
    }

    @Test
    void producesFindingsWithoutAnyPromptOrQuestion() {
        SweepRun run = sweep.run();

        assertThat(run.findings()).as("the loop starts on a tick, not a question").isNotEmpty();
        assertThat(run.runId()).isNotBlank();
        assertThat(run.feedHealth()).isNotEmpty();
    }

    @Test
    void theSameFixtureAndClockProduceIdenticalFindings() {
        SweepRun a = sweep.run();
        SweepRun b = sweep.run();

        assertThat(a.findings()).extracting(Finding::id).isEqualTo(
                b.findings().stream().map(Finding::id).toList());
        assertThat(a.findings()).extracting(Finding::observed).isEqualTo(
                b.findings().stream().map(Finding::observed).toList());
        assertThat(a.findings()).extracting(Finding::tier).isEqualTo(
                b.findings().stream().map(Finding::tier).toList());
    }

    @Test
    void findingsComeBackRanked() {
        List<Tier> tiers = sweep.run().findings().stream().map(Finding::tier).toList();

        assertThat(tiers).isSortedAccordingTo(java.util.Comparator.reverseOrder());
    }

    @Test
    void everyMetricSliceCombinationIsVisited() {
        SweepRun run = sweep.run();

        assertThat(run.findings()).extracting(Finding::metricId).as("all three active metrics")
                .contains("ota", "sla_breach", "vendor_ota");
        assertThat(run.findings()).extracting(f -> f.slice().dim())
                .as("both the overall figure and sliced ones")
                .contains(com.signaldesk.registry.Dimension.NONE,
                          com.signaldesk.registry.Dimension.VENDOR);
    }

    @Test
    void theTierDistributionAcrossTheFixtureIsPrintedForCalibration() {
        Map<Tier, Long> byTier = sweep.run().findings().stream()
                .collect(Collectors.groupingBy(Finding::tier, Collectors.counting()));

        System.out.println("MEASURED TIER DISTRIBUTION: " + byTier);
        assertThat(byTier).isNotEmpty();
    }

    @Test
    void theDegradingVendorAppearsAsAConcernOrWorse() {
        List<Finding> v07 = sweep.run().findings().stream()
                .filter(f -> FixtureGenerator.DEGRADING_VENDOR.equals(f.slice().value()))
                .toList();

        System.out.println("MEASURED V07 findings: " + v07.stream()
                .map(f -> f.metricId() + "=" + f.tier() + "@" + String.format("%.2f", f.observed()))
                .toList());

        assertThat(v07).as("the planted regression is the narrative the demo is built on")
                .anySatisfy(f -> assertThat(f.tier()).isGreaterThanOrEqualTo(Tier.CONCERN));
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=SweepTest`
Expected: FAIL — `cannot find symbol: class Sweep`.

- [ ] **Step 3: Write SweepRun and FindingStore**

`SweepRun.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.FeedHealth;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Finding;
import java.util.List;
import java.util.Map;

public record SweepRun(
        String runId,
        Window window,
        List<Finding> findings,
        Map<Feed, FeedHealth> feedHealth,
        long sweptAtMs) {

    public SweepRun {
        findings = List.copyOf(findings);
        feedHealth = Map.copyOf(feedHealth);
    }
}
```

`FindingStore.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.verdict.Finding;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.stereotype.Component;

/**
 * In-process only. Audit-log persistence is explicitly out of scope (spec 2.2):
 * the store exists so the console and the interrogation panel can re-read a run,
 * not as a system of record.
 */
@Component
public class FindingStore {

    private final Map<String, SweepRun> runs = new ConcurrentHashMap<>();
    private final Map<String, Finding> findingsById = new ConcurrentHashMap<>();
    private final AtomicReference<String> latestRunId = new AtomicReference<>();

    public void put(SweepRun run) {
        runs.put(run.runId(), run);
        run.findings().forEach(f -> findingsById.put(f.id(), f));
        latestRunId.set(run.runId());
    }

    public Optional<SweepRun> get(String runId) {
        return Optional.ofNullable(runs.get(runId));
    }

    public Optional<SweepRun> latest() {
        String id = latestRunId.get();
        return id == null ? Optional.empty() : get(id);
    }

    public Optional<Finding> finding(String findingId) {
        return Optional.ofNullable(findingsById.get(findingId));
    }

    public Collection<String> runIds() {
        return new LinkedHashMap<>(runs).keySet();
    }
}
```

- [ ] **Step 4: Write the sweep**

`Sweep.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.ingest.GapRegister;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.Metric;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.MetricRepository;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Ranker;
import com.signaldesk.verdict.VerdictEngine;
import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * The SENSE step. It iterates every (metric x slice) pair, evaluates the rules,
 * and writes findings. No prompt is involved.
 *
 * The clock is injected so the demo can drive a simulated one and the same run
 * always produces the same findings.
 */
@Component
public class Sweep {

    private static final Logger log = LoggerFactory.getLogger(Sweep.class);

    private final MetricRegistry registry;
    private final MetricRepository repo;
    private final VerdictEngine engine;
    private final GapRegister gaps;
    private final Clock clock;
    private final int windowDays;

    public Sweep(MetricRegistry registry, MetricRepository repo, VerdictEngine engine,
                 GapRegister gaps, Clock clock,
                 @org.springframework.beans.factory.annotation.Value("${signaldesk.window-days}")
                 int windowDays) {
        this.registry = registry;
        this.repo = repo;
        this.engine = engine;
        this.gaps = gaps;
        this.clock = clock;
        this.windowDays = windowDays;
    }

    public SweepRun run() {
        long now = clock.millis();
        Window window = new Window(now - windowDays * 86_400_000L, now,
                "the " + windowDays + " days to " + java.time.Instant.ofEpochMilli(now));

        List<Finding> found = new ArrayList<>();
        for (Metric metric : registry.active()) {
            engine.evaluate(metric, Slice.all(), window).ifPresent(found::add);
            for (Dimension dim : Dimension.values()) {
                if (dim == Dimension.NONE) {
                    continue;
                }
                for (String value : repo.distinctValues(dim, window)) {
                    engine.evaluate(metric, new Slice(dim, value), window).ifPresent(found::add);
                }
            }
        }

        List<Finding> ranked = Ranker.rank(found);
        String runId = "run-" + now + "-" + Integer.toHexString(ranked.size());
        log.info("sweep {} evaluated {} metric-slice pairs, kept {} findings",
                runId, registry.active().size(), ranked.size());
        return new SweepRun(runId, window, ranked, gaps.assess(), now);
    }
}
```

The `runId` is derived from the simulated clock and the finding count rather
than a UUID, so a rerun of the demo produces the same id and a bookmarked
console URL still resolves.

- [ ] **Step 5: Wire the clock, the verdict engine bean, and the scheduler**

`ClockConfig.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.fixture.FixtureGenerator;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ClockConfig {

    /**
     * The demo drives a simulated clock pinned to the end of the fixture, so the
     * same run always produces the same findings. Set signaldesk.clock=system for
     * a real deployment against live data.
     */
    @Bean
    public Clock clock(@Value("${signaldesk.clock:fixture}") String mode) {
        return "system".equals(mode)
                ? Clock.systemUTC()
                : Clock.fixed(Instant.ofEpochMilli(FixtureGenerator.windowEnd()), ZoneOffset.UTC);
    }
}
```

`VerdictConfig.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.GapRegister;
import com.signaldesk.registry.MetricRepository;
import com.signaldesk.registry.ReferenceResolver;
import com.signaldesk.verdict.VerdictEngine;
import java.util.function.ToDoubleFunction;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class VerdictConfig {

    @Bean
    public VerdictEngine verdictEngine(MetricRepository repo, ReferenceResolver resolver,
                                       GapRegister gaps) {
        ToDoubleFunction<Feed> confidence = gaps::confidenceFor;
        return new VerdictEngine(repo, resolver, confidence);
    }
}
```

`SweepScheduler.java`:

```java
package com.signaldesk.agent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class SweepScheduler {

    private static final Logger log = LoggerFactory.getLogger(SweepScheduler.class);

    private final Sweep sweep;
    private final FindingStore store;

    public SweepScheduler(Sweep sweep, FindingStore store) {
        this.sweep = sweep;
        this.store = store;
    }

    /** The console opens on a completed sweep, not an empty shell. */
    @EventListener(ApplicationReadyEvent.class)
    public void sweepOnStartup() {
        tick();
    }

    @Scheduled(cron = "${signaldesk.sweep.cron}")
    public void tick() {
        SweepRun run = sweep.run();
        store.put(run);
        log.info("stored sweep {} with {} findings", run.runId(), run.findings().size());
    }
}
```

`SweepController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.agent.Sweep;
import com.signaldesk.agent.FindingStore;
import com.signaldesk.agent.SweepRun;
import java.util.Map;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class SweepController {

    private final Sweep sweep;
    private final FindingStore store;

    public SweepController(Sweep sweep, FindingStore store) {
        this.sweep = sweep;
        this.store = store;
    }

    /**
     * The manual trigger. It exists so a judge can watch the loop fire, not
     * because the loop needs asking — the @Scheduled sweep is the real one.
     */
    @PostMapping("/sweep")
    public Map<String, Object> sweep() {
        SweepRun run = sweep.run();
        store.put(run);
        return Map.of("runId", run.runId(), "findingCount", run.findings().size());
    }
}
```

- [ ] **Step 6: Run the sweep tests and read the measurements**

Run: `./scripts/mvn.sh -q test -Dtest=SweepTest`
Expected: PASS, 6 tests. Copy the `MEASURED TIER DISTRIBUTION` and
`MEASURED V07 findings` lines somewhere — Task 10 works from them.

- [ ] **Step 7: Run the service and trigger a sweep by hand**

Run:
```bash
./scripts/mvn.sh -q spring-boot:run &
sleep 25
curl -s -X POST http://localhost:8080/api/sweep
```
Expected: `{"runId":"run-...","findingCount":N}` with N > 0, and a startup log
line showing the sweep that ran on `ApplicationReadyEvent` without anyone asking.

- [ ] **Step 8: Break-it-to-prove-it**

Change the `Clock.fixed` bean to `Clock.systemUTC()`, rerun `SweepTest`.
Expected: `theDegradingVendorAppearsAsAConcernOrWorse` FAILS — wall-clock time is
outside the fixture, so the window is empty. Restore. This is why the simulated
clock is a design decision rather than a testing convenience.

- [ ] **Step 9: Commit**

```bash
git add service
git commit -m "feat(agent): scheduled sweep on a simulated clock, plus a manual trigger for the demo"
```

---

### Task 10: Calibration — measure the thresholds, then pin them (~0 h 20)

**Files:**
- Modify: `service/src/main/java/com/signaldesk/verdict/DeltaRule.java` (threshold constants and their measurement comment)
- Modify: `service/src/test/java/com/signaldesk/agent/SweepTest.java` (pin the golden distribution)

**Interfaces:**
- Consumes: everything from Tasks 1–9.
- Produces: threshold constants that have been measured against the real fixture,
  and a golden test that fails if a later change moves the distribution.

**Spec §6.3 requires this and names the failure it prevents:** "a threshold
nobody measured either fires on everything or nothing." The bands shipped in
Task 7 are provisional. This task makes them real. It is the last task before
the checkpoint that can still change what the demo says.

- [ ] **Step 1: Read the measured distribution**

Run: `./scripts/mvn.sh -q test -Dtest=SweepTest 2>&1 | grep MEASURED`

Expected: two lines — the tier distribution across all findings, and V07's
findings with their tiers and observed values.

- [ ] **Step 2: Judge the distribution against three criteria**

The fixture must produce:

1. **A mix across all four tiers.** Every tier with at least one finding. If
   `PASS` is 95% of findings, the agent has nothing to say; if `BREACH` is 40%,
   nothing stands out and the ranking is meaningless.
2. **The planted V07 regression at `CONCERN` or `BREACH`.** This is the demo.
3. **At least one `BREACH`, and no more than about five.** A leadership brief
   with twenty breaches is a wall, not a decision.

- [ ] **Step 3: Adjust only if a criterion fails, and adjust the bands, not the fixture**

If the distribution is degenerate, change `PASS_MAX`, `WATCH_MAX`, `CONCERN_MAX`
in `DeltaRule` and rerun Step 1. Move them in whole percentage points, one at a
time.

**Do not "fix" this by editing the fixture generator.** The generator's fault
rates were themselves measured in Task 2, and changing them invalidates that
work plus the committed CSVs plus every golden number already recorded. Bands are
cheap to move; a regenerated fixture is not.

If no band setting satisfies criterion 1, the problem is upstream: the vendor
penalties in `FixtureGenerator.onTimeProbability` are too uniform to spread
across four tiers. That *is* a generator change, and it means redoing Task 2
Steps 10–12. Budget 20 extra minutes and do it now rather than at hour twelve.

- [ ] **Step 4: Record the measurement in the code**

Replace the placeholder comment in `DeltaRule` with the real figures:

```java
/**
 * ...
 * MEASURED against data/fixture at seed 20260904, window = the 7 days to
 * <window end>:
 *   PASS=<n> WATCH=<n> CONCERN=<n> BREACH=<n> across <total> findings
 *   V07 vendor_ota=<observed>% -> <TIER> against a peer median of <peer>%
 * Bands below were tuned to produce that spread. Re-measure if the fixture or
 * the metric SQL changes; do not adjust them to make a test pass.
 */
```

Fill in every angle-bracketed value from Step 1's output. **A comment with
placeholders left in it is worse than no comment**, because the next reader will
trust it.

- [ ] **Step 5: Pin the golden distribution**

Replace `theTierDistributionAcrossTheFixtureIsPrintedForCalibration` in
`SweepTest` with a pinned version:

```java
    @Test
    void theTierDistributionMatchesWhatWasMeasuredAtCalibration() {
        Map<Tier, Long> byTier = sweep.run().findings().stream()
                .collect(Collectors.groupingBy(Finding::tier, Collectors.counting()));
        System.out.println("MEASURED TIER DISTRIBUTION: " + byTier);

        // Pinned in Task 10 against seed 20260904. Bands are ~80% of the measured
        // counts, so a small metric-SQL change does not fail the build but a
        // structural one does. Measured: PASS=<n> WATCH=<n> CONCERN=<n> BREACH=<n>.
        assertThat(byTier).containsOnlyKeys(Tier.PASS, Tier.WATCH, Tier.CONCERN, Tier.BREACH);
        assertThat(byTier.get(Tier.BREACH)).isBetween(1L, 8L);
        assertThat(byTier.get(Tier.CONCERN)).isGreaterThanOrEqualTo(/* 80% of measured */ 1L);
        assertThat(byTier.get(Tier.PASS)).isGreaterThanOrEqualTo(/* 80% of measured */ 1L);
    }
```

Replace each `1L` placeholder with 80% of the measured count, rounded down, and
fill in the comment. `containsOnlyKeys` with all four tiers is the assertion that
all four are reachable **on the real fixture**, not merely in the unit tests.

- [ ] **Step 6: Run the whole suite**

Run: `./scripts/mvn.sh -q test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add service
git commit -m "test(verdict): calibrate the tier bands against the fixture and pin the distribution"
```

---

### Task 11: The thin delivery slice — a template brief on the real Slack channel (~0 h 30)

**Files:**
- Create: `service/src/main/java/com/signaldesk/agent/Composer.java`, `TemplateComposer.java`, `Dispatcher.java`, `DispatchLog.java`
- Create: `service/src/main/java/com/signaldesk/delivery/Channel.java`, `SlackChannel.java`, `DispatchResult.java`
- Create: `service/src/main/java/com/signaldesk/api/DispatchController.java`
- Test: `service/src/test/java/com/signaldesk/agent/TemplateComposerTest.java`
- Test: `service/src/test/java/com/signaldesk/agent/DispatcherTest.java`
- Modify: the committed example-env file (add `SLACK_WEBHOOK_URL`)

**Interfaces:**
- Consumes: `SweepRun`, `Finding`, `Tier`, `Audience`, `MetricRegistry`.
- Produces:
  - `interface Composer { String compose(SweepRun run, Audience audience); }`
  - `TemplateComposer` — deterministic, no model. Task 13's `SarvamComposer`
    falls back to exactly this.
  - `interface Channel { String name(); DispatchResult send(String subject, String body); }`
  - `record DispatchResult(String channel, boolean delivered, String detail)`
  - `Dispatcher.dispatch(SweepRun)` returning `List<DispatchResult>`
  - `DispatchLog.record(...)`, `DispatchLog.entries()`
  - `POST /api/dispatch/{runId}`

**This task closes the loop, and it is the last one before the checkpoint.**
Routing: `BREACH` and `CONCERN` → Slack *and* email; `WATCH` → Slack; `PASS` →
console only. Email lands in Task 14, so the email channel is registered as a
no-op that reports `delivered=false, detail="not configured"` until then — which
the dispatch log shows honestly rather than hiding.

- [ ] **Step 1: Write the failing composer tests**

`service/src/test/java/com/signaldesk/agent/TemplateComposerTest.java`:

```java
package com.signaldesk.agent;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.FeedHealth;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.ReferenceKind;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Cause;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

class TemplateComposerTest {

    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);
    private final MetricRegistry registry =
            new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));
    private final TemplateComposer composer = new TemplateComposer(registry);

    private Finding breach() {
        return new Finding("f1", "vendor_ota", new Slice(Dimension.VENDOR, "V07"), window,
                61.40, List.of(new Reference(ReferenceKind.PEER, 89.20, "peer median")),
                Tier.BREACH, Cause.PEER_LAGGARD, 27.80, 0.97,
                Set.of(Audience.FACILITIES_HEAD, Audience.TRANSPORT_MANAGER), "SELECT 1");
    }

    private Finding lowConfidence() {
        return new Finding("f2", "ota", Slice.all(), window,
                78.00, List.of(new Reference(ReferenceKind.TARGET, 90.00, "SLA target")),
                Tier.WATCH, Cause.LOW_CONFIDENCE, 12.00, 0.62,
                Set.of(Audience.TRANSPORT_MANAGER), "SELECT 1");
    }

    private SweepRun run(List<Finding> findings) {
        return new SweepRun("run-1", window, findings,
                Map.of(Feed.TRIPS, FeedHealth.of(Feed.TRIPS, 8000, 120, 0, 160)),
                window.endMs());
    }

    @Test
    void citesTheReferencePointForEveryClaim() {
        String brief = composer.compose(run(List.of(breach())), Audience.FACILITIES_HEAD);

        assertThat(brief).contains("61.40");
        assertThat(brief).as("a metric without context is just a number").contains("peer median");
        assertThat(brief).contains("89.20");
    }

    @Test
    void mentionsConfidenceOnlyWhenItIsBelowNinetyPercent() {
        String uncertain = composer.compose(run(List.of(lowConfidence())), Audience.TRANSPORT_MANAGER);
        String confident = composer.compose(run(List.of(breach())), Audience.FACILITIES_HEAD);

        assertThat(uncertain).as("a number the agent is unsure about must say so")
                .containsIgnoringCase("confidence");
        assertThat(confident).as("and must not clutter the brief when it is sure")
                .doesNotContainIgnoringCase("confidence");
    }

    @Test
    void addressesTheNamedAudienceAndIncludesOnlyTheirFindings() {
        String facilities = composer.compose(run(List.of(breach(), lowConfidence())),
                Audience.FACILITIES_HEAD);

        assertThat(facilities).contains("Facilities");
        assertThat(facilities).contains("V07");
    }

    @Test
    void introducesNoFigureThatIsNotInTheFindings() {
        // The same property Task 13 validates the model against, asserted here on
        // the deterministic path so the fallback is known-good before it is needed.
        String brief = composer.compose(run(List.of(breach())), Audience.FACILITIES_HEAD);

        List<String> numbers = java.util.regex.Pattern.compile("-?\\d+\\.\\d{2}")
                .matcher(brief).results().map(m -> m.group()).toList();

        assertThat(numbers).isNotEmpty();
        assertThat(numbers).allSatisfy(n ->
                assertThat(List.of("61.40", "89.20", "27.80")).contains(n));
    }

    @Test
    void producesAnHonestBriefWhenNothingIsWrong() {
        String brief = composer.compose(run(List.of()), Audience.TRANSPORT_MANAGER);

        assertThat(brief).isNotBlank();
        assertThat(brief).containsIgnoringCase("no findings");
    }

    @Test
    void isDeterministic() {
        SweepRun r = run(List.of(breach(), lowConfidence()));

        assertThat(composer.compose(r, Audience.FACILITIES_HEAD))
                .isEqualTo(composer.compose(r, Audience.FACILITIES_HEAD));
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=TemplateComposerTest`
Expected: FAIL — `cannot find symbol: class TemplateComposer`.

- [ ] **Step 3: Write the composer interface and the template implementation**

`Composer.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.verdict.Audience;

public interface Composer {
    String compose(SweepRun run, Audience audience);
}
```

`TemplateComposer.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.registry.Metric;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * The deterministic brief. It is both the pre-checkpoint delivery path and the
 * fallback Task 13 substitutes when the model's narrative fails validation:
 * a wrong number in a leadership brief is worse than plain prose.
 */
@Component
public class TemplateComposer implements Composer {

    private final MetricRegistry registry;

    public TemplateComposer(MetricRegistry registry) {
        this.registry = registry;
    }

    @Override
    public String compose(SweepRun run, Audience audience) {
        List<Finding> mine = run.findings().stream()
                .filter(f -> f.audiences().contains(audience))
                .filter(f -> f.tier() != Tier.PASS)
                .toList();

        StringBuilder sb = new StringBuilder();
        sb.append(salutation(audience)).append('\n')
          .append("Commute operations, ").append(run.window().label()).append('\n');

        if (mine.isEmpty()) {
            sb.append("\nNo findings above PASS in this window. ")
              .append("Every metric is at or better than its reference points.\n");
            return sb.toString();
        }

        sb.append('\n').append(mine.size()).append(" item")
          .append(mine.size() == 1 ? "" : "s").append(" need attention.\n");

        for (Finding f : mine) {
            Metric m = registry.byId(f.metricId());
            sb.append('\n')
              .append("[").append(f.tier()).append("] ").append(m.label())
              .append(" — ").append(f.slice().label()).append('\n')
              .append("  ").append(format(f.observed())).append(m.unit().equals("%") ? "%" : " " + m.unit());
            for (Reference ref : f.refs()) {
                sb.append(", against a ").append(ref.label()).append(" of ")
                  .append(format(ref.value())).append(m.unit().equals("%") ? "%" : "");
            }
            sb.append(".\n").append("  Cause: ").append(humanise(f.cause())).append('\n');
            if (f.mustDiscloseConfidence()) {
                sb.append("  Confidence in this figure is ")
                  .append(format(f.confidence() * 100)).append("% — ")
                  .append("some source rows were unreadable or unmatched.\n");
            }
        }
        return sb.toString();
    }

    private static String salutation(Audience audience) {
        return switch (audience) {
            case FACILITIES_HEAD -> "For the Transport & Facilities Head:";
            case TRANSPORT_MANAGER -> "For the Transport Manager:";
            case LINE_MANAGER -> "For the Line Manager:";
        };
    }

    private static String humanise(com.signaldesk.verdict.Cause cause) {
        return switch (cause) {
            case BELOW_TARGET -> "below the declared target";
            case TREND_REGRESSION -> "worse than its own recent trend";
            case PEER_LAGGARD -> "behind comparable peers";
            case LOW_CONFIDENCE -> "flagged, but the source data is incomplete";
            case DATA_GAP -> "could not be measured from the data available";
            case ON_REFERENCE -> "within its reference points";
        };
    }

    private static String format(double d) {
        return String.format("%.2f", d);
    }
}
```

- [ ] **Step 4: Run the composer tests**

Run: `./scripts/mvn.sh -q test -Dtest=TemplateComposerTest`
Expected: PASS, 6 tests.

- [ ] **Step 5: Write the failing dispatcher tests**

`service/src/test/java/com/signaldesk/agent/DispatcherTest.java`:

```java
package com.signaldesk.agent;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.delivery.Channel;
import com.signaldesk.delivery.DispatchResult;
import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.FeedHealth;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Cause;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

class DispatcherTest {

    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);
    private final MetricRegistry registry =
            new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));

    static class RecordingChannel implements Channel {
        final String name;
        final List<String> sent = new ArrayList<>();
        boolean fail;

        RecordingChannel(String name) {
            this.name = name;
        }

        @Override public String name() { return name; }

        @Override public DispatchResult send(String subject, String body) {
            if (fail) {
                throw new RuntimeException("channel " + name + " is down");
            }
            sent.add(body);
            return new DispatchResult(name, true, "ok");
        }
    }

    private Finding at(Tier tier, String id) {
        return new Finding(id, "ota", Slice.all(), window, 78.0,
                List.of(new Reference(com.signaldesk.registry.ReferenceKind.TARGET, 90.0, "SLA target")),
                tier, tier == Tier.PASS ? Cause.ON_REFERENCE : Cause.BELOW_TARGET,
                tier == Tier.PASS ? -1.0 : 12.0, 0.97,
                Set.of(Audience.TRANSPORT_MANAGER), "SELECT 1");
    }

    private SweepRun run(List<Finding> findings) {
        return new SweepRun("run-1", window, findings,
                Map.of(Feed.TRIPS, FeedHealth.of(Feed.TRIPS, 100, 0, 0, 0)), window.endMs());
    }

    @Test
    void breachAndConcernGoToBothChannels() {
        RecordingChannel slack = new RecordingChannel("slack");
        RecordingChannel email = new RecordingChannel("email");
        Dispatcher d = new Dispatcher(new TemplateComposer(registry), List.of(slack, email),
                new DispatchLog());

        d.dispatch(run(List.of(at(Tier.BREACH, "b"))));

        assertThat(slack.sent).hasSize(1);
        assertThat(email.sent).hasSize(1);
    }

    @Test
    void watchGoesToSlackOnly() {
        RecordingChannel slack = new RecordingChannel("slack");
        RecordingChannel email = new RecordingChannel("email");
        Dispatcher d = new Dispatcher(new TemplateComposer(registry), List.of(slack, email),
                new DispatchLog());

        d.dispatch(run(List.of(at(Tier.WATCH, "w"))));

        assertThat(slack.sent).hasSize(1);
        assertThat(email.sent).as("a WATCH does not warrant an email").isEmpty();
    }

    @Test
    void passGoesNowhere() {
        RecordingChannel slack = new RecordingChannel("slack");
        Dispatcher d = new Dispatcher(new TemplateComposer(registry), List.of(slack),
                new DispatchLog());

        d.dispatch(run(List.of(at(Tier.PASS, "p"))));

        assertThat(slack.sent).as("PASS is console-only").isEmpty();
    }

    @Test
    void aChannelFailureIsRecordedAndDoesNotLoseTheFindingOrBlockTheOtherChannel() {
        RecordingChannel slack = new RecordingChannel("slack");
        slack.fail = true;
        RecordingChannel email = new RecordingChannel("email");
        DispatchLog log = new DispatchLog();
        Dispatcher d = new Dispatcher(new TemplateComposer(registry), List.of(slack, email), log);
        SweepRun r = run(List.of(at(Tier.BREACH, "b")));

        List<DispatchResult> results = d.dispatch(r);

        assertThat(results).anySatisfy(res -> {
            assertThat(res.channel()).isEqualTo("slack");
            assertThat(res.delivered()).isFalse();
            assertThat(res.detail()).contains("is down");
        });
        assertThat(email.sent).as("one channel failing must not silence the other").hasSize(1);
        assertThat(r.findings()).as("the finding survives a failed send").hasSize(1);
        assertThat(log.entries()).isNotEmpty();
    }

    @Test
    void everyDispatchRecordsWhatWasSentToWhomAndFromWhichFindings() {
        DispatchLog log = new DispatchLog();
        Dispatcher d = new Dispatcher(new TemplateComposer(registry),
                List.of(new RecordingChannel("slack")), log);

        d.dispatch(run(List.of(at(Tier.BREACH, "b1"), at(Tier.WATCH, "w1"))));

        assertThat(log.entries()).allSatisfy(e -> {
            assertThat(e.channel()).isNotBlank();
            assertThat(e.audience()).isNotNull();
            assertThat(e.findingIds()).isNotEmpty();
        });
    }
}
```

- [ ] **Step 6: Write the channel, the dispatcher and the log**

`Channel.java`:

```java
package com.signaldesk.delivery;

public interface Channel {
    String name();

    DispatchResult send(String subject, String body);
}
```

`DispatchResult.java`:

```java
package com.signaldesk.delivery;

public record DispatchResult(String channel, boolean delivered, String detail) {}
```

`SlackChannel.java`:

```java
package com.signaldesk.delivery;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * The primary delivery channel: a real incoming webhook, not a mock.
 *
 * The URL is a credential in its own right — anyone holding it can post to the
 * channel — so it comes from the environment and is never logged.
 */
@Component
public class SlackChannel implements Channel {

    private final String webhookUrl;
    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5)).build();

    public SlackChannel(@Value("${SLACK_WEBHOOK_URL:}") String webhookUrl) {
        this.webhookUrl = webhookUrl;
    }

    @Override
    public String name() {
        return "slack";
    }

    @Override
    public DispatchResult send(String subject, String body) {
        if (webhookUrl.isBlank()) {
            return new DispatchResult(name(), false, "SLACK_WEBHOOK_URL not set");
        }
        String payload = "{\"text\":" + jsonString("*" + subject + "*\n" + body) + "}";
        HttpRequest req = HttpRequest.newBuilder(URI.create(webhookUrl))
                .header("Content-Type", "application/json")
                .timeout(Duration.ofSeconds(10))
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();
        try {
            HttpResponse<String> res = http.send(req, HttpResponse.BodyHandlers.ofString());
            boolean ok = res.statusCode() / 100 == 2;
            // The URL is deliberately absent from this detail string.
            return new DispatchResult(name(), ok, "HTTP " + res.statusCode() + " " + res.body());
        } catch (Exception e) {
            return new DispatchResult(name(), false, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    private static String jsonString(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.append('"').toString();
    }
}
```

`DispatchLog.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.verdict.Audience;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import org.springframework.stereotype.Component;

/** What was sent, to whom, and the findings it was derived from. */
@Component
public class DispatchLog {

    public record Entry(String runId, String channel, Audience audience,
                        Set<String> findingIds, boolean delivered, String detail) {}

    private final List<Entry> entries = new CopyOnWriteArrayList<>();

    public void record(Entry entry) {
        entries.add(entry);
    }

    public List<Entry> entries() {
        return List.copyOf(entries);
    }
}
```

`Dispatcher.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.delivery.Channel;
import com.signaldesk.delivery.DispatchResult;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Tier;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/** The ACT step. Routes by tier and records every dispatch. */
@Component
public class Dispatcher {

    private static final Logger log = LoggerFactory.getLogger(Dispatcher.class);

    private final Composer composer;
    private final List<Channel> channels;
    private final DispatchLog dispatchLog;

    public Dispatcher(Composer composer, List<Channel> channels, DispatchLog dispatchLog) {
        this.composer = composer;
        this.channels = channels;
        this.dispatchLog = dispatchLog;
    }

    public List<DispatchResult> dispatch(SweepRun run) {
        List<DispatchResult> results = new ArrayList<>();
        for (Audience audience : Audience.values()) {
            List<Finding> mine = run.findings().stream()
                    .filter(f -> f.audiences().contains(audience))
                    .filter(f -> f.tier() != Tier.PASS)
                    .toList();
            if (mine.isEmpty()) {
                continue;
            }
            Tier worst = mine.stream().map(Finding::tier).max(Tier::compareTo).orElse(Tier.PASS);
            Set<String> ids = mine.stream().map(Finding::id).collect(Collectors.toSet());
            String body = composer.compose(run, audience);
            String subject = "Signal Desk — " + worst + " — " + run.window().label();

            for (Channel channel : channelsFor(worst)) {
                DispatchResult result = safeSend(channel, subject, body);
                results.add(result);
                dispatchLog.record(new DispatchLog.Entry(run.runId(), channel.name(), audience,
                        ids, result.delivered(), result.detail()));
                if (!result.delivered()) {
                    log.warn("dispatch to {} for {} failed: {}",
                            channel.name(), audience, result.detail());
                }
            }
        }
        return results;
    }

    /** BREACH and CONCERN go everywhere; WATCH is Slack only; PASS never reaches here. */
    private List<Channel> channelsFor(Tier worst) {
        if (worst.compareTo(Tier.CONCERN) >= 0) {
            return channels;
        }
        return channels.stream().filter(c -> "slack".equals(c.name())).toList();
    }

    /** A send failure is recorded; it never loses the finding or stops the next channel. */
    private DispatchResult safeSend(Channel channel, String subject, String body) {
        try {
            return channel.send(subject, body);
        } catch (RuntimeException e) {
            return new DispatchResult(channel.name(), false,
                    e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }
}
```

`DispatchController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.agent.Dispatcher;
import com.signaldesk.agent.FindingStore;
import com.signaldesk.delivery.DispatchResult;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class DispatchController {

    private final Dispatcher dispatcher;
    private final FindingStore store;

    public DispatchController(Dispatcher dispatcher, FindingStore store) {
        this.dispatcher = dispatcher;
        this.store = store;
    }

    @PostMapping("/dispatch/{runId}")
    public ResponseEntity<List<DispatchResult>> dispatch(@PathVariable String runId) {
        return store.get(runId)
                .map(run -> ResponseEntity.ok(dispatcher.dispatch(run)))
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
```

- [ ] **Step 7: Run the dispatcher tests**

Run: `./scripts/mvn.sh -q test -Dtest=DispatcherTest`
Expected: PASS, 5 tests.

- [ ] **Step 8: Add the environment placeholder**

Append to the committed example-env file (create it if absent), values as
placeholders only:

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/REPLACE/ME/PLACEHOLDER
SARVAM_API_KEY=replace-me
SES_FROM=replace-me@example.com
SES_TO=teammate-one@example.com,teammate-two@example.com
```

Confirm the file is not ignored and carries no real value:
`git check-ignore -v .env.example || echo "tracked"` then
`grep -c hooks.slack.com/services/REPLACE .env.example`.

- [ ] **Step 9: Close the loop for real**

Run:
```bash
export SLACK_WEBHOOK_URL='...'          # from the environment, never from a file in git
./scripts/mvn.sh -q spring-boot:run &
sleep 25
RUN=$(curl -s -X POST http://localhost:8080/api/sweep | sed 's/.*"runId":"\([^"]*\)".*/\1/')
curl -s -X POST "http://localhost:8080/api/dispatch/$RUN"
```
Expected: a JSON array showing `"channel":"slack","delivered":true`, **and the
brief visible in the Slack channel.** Read the message: it must name a specific
vendor, quote a reference point, and be forwardable without editing.

If the brief reads like a data dump rather than something a manager would act
on, fix the template now. This wording is what the demo is judged on, and it is
cheaper to fix here than after Task 13 layers a model on top of it.

- [ ] **Step 10: Break-it-to-prove-it**

Change `channelsFor` to always return all channels, rerun `DispatcherTest`.
Expected: `watchGoesToSlackOnly` FAILS. Restore.

Change `safeSend` to let the exception propagate, rerun. Expected:
`aChannelFailureIsRecordedAndDoesNotLoseTheFindingOrBlockTheOtherChannel` FAILS.
Restore.

- [ ] **Step 11: Commit**

```bash
git add service .env.example
git commit -m "feat(agent): close the loop — template brief dispatched to the real Slack channel"
```

---

## ⛔ CHECKPOINT — stop here and demo it

**Do not start Task 12 until every line below is checked.** This is the thing
the whole plan protects. If it is 09:00 and the gate is red, keep working on
Phase 1; if it is 06:00 and the gate is green, start Phase 2 early.

- [ ] `./scripts/mvn.sh test` is **green**, whole suite, no skips other than the
      documented `experience` skip
- [ ] `git log --oneline` shows **eleven task commits** and a clean tree
- [ ] The service starts and **sweeps once on startup with no prompt** — point at
      the log line
- [ ] `POST /api/sweep` returns a runId and a non-zero finding count
- [ ] `POST /api/dispatch/{runId}` puts a brief **in the real Slack channel**
- [ ] That brief **names the degrading vendor**, cites a reference point, and
      discloses confidence where it is below 0.9
- [ ] The tier distribution across the fixture covers **all four tiers**, and the
      measured figures are recorded in `DeltaRule`'s comment — no placeholders
      left in it
- [ ] Every guard has been through **break-it-to-prove-it** at least once
- [ ] No credential appears in `git log -p` — check with
      `git log -p | grep -iE 'hooks.slack.com/services/[A-Z0-9]|sk-|Bearer [A-Za-z0-9]' | grep -v REPLACE`
      and expect no output

**Then, before touching Phase 2, do the two-minute version of the demo out loud.**
"It swept without being asked. It found this. Here is the query it used. It sent
this to Slack." If that sentence does not land in two minutes, the problem is the
brief's wording, not a missing feature — and no Phase 2 task fixes it.

**Finally, check the estimate, not the scope.** Scope is settled: all 22 tasks
ship. What Phase 1 tells you is whether the *estimates* hold. Compare elapsed
time against 7 h 10. If you are inside it, carry on. If you are more than ~30%
over, the 17 h 25 total is optimistic rather than the timebox being small, and
that is the trigger to re-open the scope decision recorded near the top of this
plan — with the person writing the deck in the room, so the story never promises
something the build has stopped pursuing.

---

# PHASE 2 — Additive, in priority order (Tasks 12–24)

Every task here widens a loop that already works. **All of it ships** — the scope
decision at the top of this plan extended the time rather than cutting the tail.
The order is retained as a **safety net**: if the extension turns out shorter
than hoped, stopping where you are lands in the least damaging place. Do not
reorder to front-load the interesting tasks; that trades the net for nothing.
Task 24 is reserved — start it 1 h 30 before the deadline regardless of what is
unfinished.

---

### Task 12: Sarvam behind a swappable interface (~0 h 45)

**Files:**
- Create: `service/src/main/java/com/signaldesk/model/ModelClient.java`, `SarvamClient.java`, `ChatMessage.java`
- Modify: `service/pom.xml` (OpenAI Java SDK)
- Test: `service/src/test/java/com/signaldesk/model/SarvamClientLiveTest.java`

**Interfaces:**
- Consumes: `SARVAM_API_KEY`.
- Produces:
  - `record ChatMessage(String role, String content)`
  - `interface ModelClient { String complete(List<ChatMessage> messages); boolean supportsToolCalling(); }`
  - `SarvamClient.MODEL = "sarvam-105b"`, `SarvamClient.BASE_URL = "https://api.sarvam.ai/v1"`

The rest of the code depends on `ModelClient`, never on Sarvam — which the §1.1
invariant makes safe. A weaker model narrating settled findings is fine; a
stronger model computing figures would not be.

- [ ] **Step 1: Resolve the SDK version rather than guessing it**

Run:
```bash
curl -s 'https://search.maven.org/solrsearch/select?q=g:com.openai+AND+a:openai-java&rows=1&wt=json' \
  | sed 's/.*"latestVersion":"\([^"]*\)".*/\1/'
```
Expected: a version string. Put it in the POM as `<openai.version>` and **record
it in the commit message**. If the search API is unreachable, run
`./scripts/mvn.sh dependency:get -Dartifact=com.openai:openai-java:LATEST` and
read the version it resolves.

Add to `pom.xml` dependencies:

```xml
    <dependency>
      <groupId>com.openai</groupId>
      <artifactId>openai-java</artifactId>
      <version>${openai.version}</version>
    </dependency>
```

- [ ] **Step 2: Write the live verification test**

`service/src/test/java/com/signaldesk/model/SarvamClientLiveTest.java`:

```java
package com.signaldesk.model;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * Hits the real API. Skips cleanly when SARVAM_API_KEY is unset, so the suite
 * stays green offline — the venue network is assumed unreliable.
 */
class SarvamClientLiveTest {

    private static String key() {
        return System.getenv("SARVAM_API_KEY");
    }

    @Test
    void completesAPromptAgainstTheRealModel() {
        assumeTrue(key() != null && !key().isBlank(), "SARVAM_API_KEY not set");

        String out = new SarvamClient(key()).complete(List.of(
                new ChatMessage("system", "Reply with exactly the word READY and nothing else."),
                new ChatMessage("user", "Are you there?")));

        assertThat(out).containsIgnoringCase("READY");
    }

    @Test
    void theKeyAuthenticatesOverBearerWhichIsThePathTheSdkTakes() {
        assumeTrue(key() != null && !key().isBlank(), "SARVAM_API_KEY not set");

        assertThat(new SarvamClient(key()).supportsToolCalling())
                .as("tool calling is the one capability the interrogation panel cannot be built without")
                .isTrue();
    }
}
```

- [ ] **Step 3: Write the client**

`ChatMessage.java`:

```java
package com.signaldesk.model;

public record ChatMessage(String role, String content) {}
```

`ModelClient.java`:

```java
package com.signaldesk.model;

import java.util.List;

/**
 * The model layer's whole surface. It produces language; it never produces a
 * figure and never sees a raw row.
 */
public interface ModelClient {

    String complete(List<ChatMessage> messages);

    boolean supportsToolCalling();
}
```

`SarvamClient.java`:

```java
package com.signaldesk.model;

import com.openai.client.OpenAIClient;
import com.openai.client.okhttp.OpenAIOkHttpClient;
import com.openai.models.chat.completions.ChatCompletion;
import com.openai.models.chat.completions.ChatCompletionCreateParams;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Sarvam's API is OpenAI-compatible, so the official OpenAI Java SDK is used with
 * a base-URL override. Sarvam-M is deprecated and no longer served; sarvam-105b
 * is the model.
 *
 * No retry, no backoff, no circuit breaker: explicitly out of scope (spec 2.2).
 * A failed call degrades to the template brief, which is a better answer than a
 * slow one.
 */
@Component
public class SarvamClient implements ModelClient {

    public static final String BASE_URL = "https://api.sarvam.ai/v1";
    public static final String MODEL = "sarvam-105b";

    private final OpenAIClient client;

    public SarvamClient(@Value("${SARVAM_API_KEY:}") String apiKey) {
        this.client = OpenAIOkHttpClient.builder()
                .baseUrl(BASE_URL)
                .apiKey(apiKey)
                .build();
    }

    @Override
    public String complete(List<ChatMessage> messages) {
        ChatCompletionCreateParams.Builder params = ChatCompletionCreateParams.builder()
                .model(MODEL)
                .maxCompletionTokens(700);
        for (ChatMessage m : messages) {
            if ("system".equals(m.role())) {
                params.addSystemMessage(m.content());
            } else {
                params.addUserMessage(m.content());
            }
        }
        ChatCompletion completion = client.chat().completions().create(params.build());
        return completion.choices().stream()
                .findFirst()
                .flatMap(c -> c.message().content())
                .orElse("");
    }

    @Override
    public boolean supportsToolCalling() {
        return true;   // verified against the live API in preflight; see the live test
    }
}
```

**The SDK's builder method names move between versions.** If `addSystemMessage`,
`maxCompletionTokens`, or the `chat().completions()` path does not compile, run
`./scripts/mvn.sh dependency:sources` and read the actual `ChatCompletionCreateParams`
builder. Do not spend more than fifteen minutes on this: if the SDK fights back,
replace `SarvamClient`'s body with a direct `java.net.http.HttpClient` POST to
`BASE_URL + "/chat/completions"` with an `Authorization: Bearer` header. The
interface is the contract; the transport is not.

- [ ] **Step 4: Run the live test**

Run: `./scripts/mvn.sh -q test -Dtest=SarvamClientLiveTest`
Expected: PASS with a real key exported; SKIPPED without one. Both are green.

- [ ] **Step 5: Confirm the whole suite still passes offline**

Run: `unset SARVAM_API_KEY && ./scripts/mvn.sh -q test`
Expected: PASS, with the two live tests skipped. **Every demo path must work
offline**, so a suite that needs the network is a defect.

- [ ] **Step 6: Commit**

```bash
git add service
git commit -m "feat(model): Sarvam behind a swappable ModelClient (openai-java <version>)"
```

---

### Task 13: The composed narrative, validated against the findings (~1 h 00)

**Files:**
- Create: `service/src/main/java/com/signaldesk/agent/NarrativeValidator.java`, `SarvamComposer.java`
- Test: `service/src/test/java/com/signaldesk/agent/NarrativeValidatorTest.java`
- Test: `service/src/test/java/com/signaldesk/agent/SarvamComposerTest.java`
- Modify: `VerdictConfig` or add `@Primary` so `Dispatcher` receives `SarvamComposer`

**Interfaces:**
- Consumes: `ModelClient`, `SweepRun`, `TemplateComposer`.
- Produces:
  - `NarrativeValidator.validate(String narrative, SweepRun run)` returning
    `Optional<String>` — the offending figure when validation fails, empty when it passes
  - `SarvamComposer implements Composer` — model narrative when valid, template when not

**One Sarvam call per brief.** Input is the ranked findings serialised compactly,
**never raw rows** — which is the cost-at-scale story: tokens per interaction stay
flat as row counts grow.

- [ ] **Step 1: Write the failing validator tests**

`service/src/test/java/com/signaldesk/agent/NarrativeValidatorTest.java`:

```java
package com.signaldesk.agent;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.FeedHealth;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.ReferenceKind;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Cause;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.junit.jupiter.api.Test;

class NarrativeValidatorTest {

    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);

    private SweepRun run() {
        Finding f = new Finding("f1", "vendor_ota", new Slice(Dimension.VENDOR, "V07"), window,
                61.40, List.of(new Reference(ReferenceKind.PEER, 89.20, "peer median")),
                Tier.BREACH, Cause.PEER_LAGGARD, 27.80, 0.97,
                Set.of(Audience.FACILITIES_HEAD), "SELECT 1");
        return new SweepRun("run-1", window, List.of(f),
                Map.of(Feed.TRIPS, FeedHealth.of(Feed.TRIPS, 100, 0, 0, 0)), window.endMs());
    }

    @Test
    void acceptsANarrativeWhoseEveryFigureIsInTheFindings() {
        Optional<String> bad = NarrativeValidator.validate(
                "V07 came in at 61.40% against a peer median of 89.20%, a shortfall of 27.80 points.",
                run());

        assertThat(bad).isEmpty();
    }

    @Test
    void rejectsANarrativeThatInventsAFigure() {
        Optional<String> bad = NarrativeValidator.validate(
                "V07 came in at 61.40%, down from 94.30% last month.", run());

        assertThat(bad).as("94.30 appears nowhere in the findings").contains("94.30");
    }

    @Test
    void rejectsAFigureThatIsCloseButNotEqualToTwoDecimalPlaces() {
        // The dangerous case: a plausible number a reader would never question.
        Optional<String> bad = NarrativeValidator.validate(
                "V07 came in at 61.42% against a peer median of 89.20%.", run());

        assertThat(bad).contains("61.42");
    }

    @Test
    void allowsTheConfidenceFigureExpressedAsAPercentage() {
        Optional<String> bad = NarrativeValidator.validate(
                "V07 came in at 61.40%, and confidence in this figure is 97.00%.", run());

        assertThat(bad).isEmpty();
    }

    @Test
    void ignoresDatesAndIntegersThatAreNotClaimsAboutMetrics() {
        Optional<String> bad = NarrativeValidator.validate(
                "In the week to 2026-09-04, 1 vendor was flagged: V07 at 61.40%.", run());

        assertThat(bad).as("the year and the count are not metric claims").isEmpty();
    }

    @Test
    void toleratesTrailingZeroDifferences() {
        Optional<String> bad = NarrativeValidator.validate("V07 came in at 61.4%.", run());

        assertThat(bad).isEmpty();
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=NarrativeValidatorTest`
Expected: FAIL — `cannot find symbol: class NarrativeValidator`.

- [ ] **Step 3: Write the validator**

`NarrativeValidator.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import java.util.HashSet;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Every number appearing in the narrative must match a figure in the findings to
 * two decimal places. If validation fails, the brief is sent from the
 * deterministic template instead: a wrong number in a leadership brief is worse
 * than plain prose.
 */
public final class NarrativeValidator {

    /** ISO dates are stripped before scanning; they are not metric claims. */
    private static final Pattern ISO_DATE = Pattern.compile("\\d{4}-\\d{2}-\\d{2}");
    /** Only decimals are treated as metric claims. Bare integers are counts and years. */
    private static final Pattern DECIMAL = Pattern.compile("-?\\d+\\.\\d+");

    private NarrativeValidator() {}

    public static Optional<String> validate(String narrative, SweepRun run) {
        Set<String> allowed = allowedFigures(run);
        Matcher m = DECIMAL.matcher(ISO_DATE.matcher(narrative).replaceAll(""));
        while (m.find()) {
            String raw = m.group();
            if (!allowed.contains(round(Double.parseDouble(raw)))) {
                return Optional.of(raw);
            }
        }
        return Optional.empty();
    }

    private static Set<String> allowedFigures(SweepRun run) {
        Set<String> out = new HashSet<>();
        for (Finding f : run.findings()) {
            out.add(round(f.observed()));
            out.add(round(f.gap()));
            out.add(round(Math.abs(f.gap())));
            out.add(round(f.confidence()));
            out.add(round(f.confidence() * 100));
            for (Reference ref : f.refs()) {
                out.add(round(ref.value()));
            }
        }
        run.feedHealth().values().forEach(h -> {
            out.add(round(h.confidence()));
            out.add(round(h.confidence() * 100));
        });
        return out;
    }

    private static String round(double d) {
        return String.format("%.2f", d);
    }
}
```

Rounding both sides to two decimal places is what makes `61.4` and `61.40` the
same figure while keeping `61.42` a different one.

- [ ] **Step 4: Run the validator tests**

Run: `./scripts/mvn.sh -q test -Dtest=NarrativeValidatorTest`
Expected: PASS, 6 tests.

- [ ] **Step 5: Write the failing composer tests**

`service/src/test/java/com/signaldesk/agent/SarvamComposerTest.java`:

```java
package com.signaldesk.agent;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.FeedHealth;
import com.signaldesk.model.ChatMessage;
import com.signaldesk.model.ModelClient;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.ReferenceKind;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Cause;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

class SarvamComposerTest {

    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);
    private final MetricRegistry registry =
            new MetricRegistry(List.of("ota", "sla_breach", "vendor_ota"));

    static class StubModel implements ModelClient {
        String reply = "";
        List<ChatMessage> lastPrompt = List.of();
        boolean throwOnCall;

        @Override public String complete(List<ChatMessage> messages) {
            if (throwOnCall) {
                throw new RuntimeException("model unreachable");
            }
            lastPrompt = messages;
            return reply;
        }

        @Override public boolean supportsToolCalling() { return true; }
    }

    private SweepRun run() {
        Finding f = new Finding("f1", "vendor_ota", new Slice(Dimension.VENDOR, "V07"), window,
                61.40, List.of(new Reference(ReferenceKind.PEER, 89.20, "peer median")),
                Tier.BREACH, Cause.PEER_LAGGARD, 27.80, 0.97,
                Set.of(Audience.FACILITIES_HEAD), "SELECT vendor_ota FROM trips");
        return new SweepRun("run-1", window, List.of(f),
                Map.of(Feed.TRIPS, FeedHealth.of(Feed.TRIPS, 100, 0, 0, 0)), window.endMs());
    }

    @Test
    void usesTheModelNarrativeWhenEveryFigureChecksOut() {
        StubModel model = new StubModel();
        model.reply = "V07 is at 61.40% against a peer median of 89.20%. Move volume off it.";

        String brief = new SarvamComposer(model, new TemplateComposer(registry)).compose(
                run(), Audience.FACILITIES_HEAD);

        assertThat(brief).contains("Move volume off it");
    }

    @Test
    void substitutesTheTemplateWhenTheModelInventsAFigure() {
        StubModel model = new StubModel();
        model.reply = "V07 is at 61.40%, down from 94.30% last month.";

        String brief = new SarvamComposer(model, new TemplateComposer(registry)).compose(
                run(), Audience.FACILITIES_HEAD);

        assertThat(brief).as("a wrong number in a leadership brief is worse than plain prose")
                .doesNotContain("94.30")
                .contains("[BREACH]");
    }

    @Test
    void substitutesTheTemplateWhenTheModelIsUnreachable() {
        StubModel model = new StubModel();
        model.throwOnCall = true;

        String brief = new SarvamComposer(model, new TemplateComposer(registry)).compose(
                run(), Audience.FACILITIES_HEAD);

        assertThat(brief).as("every demo path works offline").contains("[BREACH]");
    }

    @Test
    void sendsFindingsRatherThanRawRowsAndMakesOneCall() {
        StubModel model = new StubModel();
        model.reply = "V07 is at 61.40% against a peer median of 89.20%.";

        new SarvamComposer(model, new TemplateComposer(registry)).compose(run(), Audience.FACILITIES_HEAD);

        String prompt = model.lastPrompt.stream().map(ChatMessage::content)
                .reduce("", (a, b) -> a + "\n" + b);
        assertThat(prompt).contains("vendor_ota").contains("61.40").contains("peer median");
        assertThat(prompt).as("aggregates, not rows — this is the cost-at-scale story")
                .doesNotContain("trip_id");
        assertThat(prompt).doesNotContain("SELECT");
    }

    @Test
    void instructsTheModelNotToIntroduceFigures() {
        StubModel model = new StubModel();
        model.reply = "V07 is at 61.40%.";

        new SarvamComposer(model, new TemplateComposer(registry)).compose(run(), Audience.FACILITIES_HEAD);

        String system = model.lastPrompt.get(0).content();
        assertThat(system).containsIgnoringCase("do not introduce");
        assertThat(system).containsIgnoringCase("reference");
    }
}
```

`sendsFindingsRatherThanRawRowsAndMakesOneCall` asserting the prompt contains no
`SELECT` is deliberate: `evidenceSql` is on the finding, and leaking it into the
prompt would hand the model raw SQL to imitate.

- [ ] **Step 6: Write the composer**

`SarvamComposer.java`:

```java
package com.signaldesk.agent;

import com.signaldesk.model.ChatMessage;
import com.signaldesk.model.ModelClient;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

@Component
@Primary
public class SarvamComposer implements Composer {

    private static final Logger log = LoggerFactory.getLogger(SarvamComposer.class);

    private static final String SYSTEM = """
            You write a short operations brief for a named reader at an enterprise
            commute operator. You are given findings that have already been computed
            and settled. Your job is language, not arithmetic.

            Rules:
            - Write for the named audience, in plain professional English.
            - Cite the reference point for every claim (the target, the 4-week
              average, or the peer median), by name.
            - Where a finding's confidence is below 0.9, say the figure is uncertain
              and why.
            - Do not introduce any figure that is not present in the findings below.
              Do not estimate, extrapolate, round differently, or compute anything.
            - No bullet lists longer than five items. No headings. Under 200 words.
            - End with one sentence naming the action the reader should take.
            """;

    private final ModelClient model;
    private final TemplateComposer fallback;

    public SarvamComposer(ModelClient model, TemplateComposer fallback) {
        this.model = model;
        this.fallback = fallback;
    }

    @Override
    public String compose(SweepRun run, Audience audience) {
        List<Finding> mine = run.findings().stream()
                .filter(f -> f.audiences().contains(audience))
                .filter(f -> f.tier() != Tier.PASS)
                .toList();
        if (mine.isEmpty()) {
            return fallback.compose(run, audience);
        }

        String narrative;
        try {
            narrative = model.complete(List.of(
                    new ChatMessage("system", SYSTEM),
                    new ChatMessage("user", serialise(mine, audience, run))));
        } catch (RuntimeException e) {
            log.warn("model unreachable, sending the template brief: {}", e.getMessage());
            return fallback.compose(run, audience);
        }

        Optional<String> offending = NarrativeValidator.validate(narrative, run);
        if (offending.isPresent()) {
            log.warn("narrative rejected: figure {} is not in the findings; sending the template",
                    offending.get());
            return fallback.compose(run, audience);
        }
        return narrative;
    }

    /** Compact, aggregate-only. One call per brief, never one per row. */
    private static String serialise(List<Finding> findings, Audience audience, SweepRun run) {
        StringBuilder sb = new StringBuilder();
        sb.append("Audience: ").append(audience).append('\n')
          .append("Window: ").append(run.window().label()).append('\n')
          .append("Findings, worst first:\n");
        for (Finding f : findings) {
            sb.append("- ").append(f.metricId()).append(" [").append(f.slice().label()).append("] ")
              .append("observed=").append(String.format("%.2f", f.observed()))
              .append(" tier=").append(f.tier())
              .append(" cause=").append(f.cause())
              .append(" confidence=").append(String.format("%.2f", f.confidence()));
            for (Reference ref : f.refs()) {
                sb.append(" | ").append(ref.label()).append("=")
                  .append(String.format("%.2f", ref.value()));
            }
            sb.append('\n');
        }
        return sb.toString();
    }
}
```

- [ ] **Step 7: Run the composer tests, then the whole suite**

Run: `./scripts/mvn.sh -q test -Dtest=SarvamComposerTest`
Expected: PASS, 5 tests.

Run: `./scripts/mvn.sh -q test`
Expected: PASS. `@Primary` means `Dispatcher` now receives `SarvamComposer`, so
`DispatcherTest`'s explicit `TemplateComposer` construction still holds.

- [ ] **Step 8: Send one real model-composed brief**

Run the service with both `SARVAM_API_KEY` and `SLACK_WEBHOOK_URL` set, sweep,
dispatch, and read the Slack message. Then check the log for
`narrative rejected` — **if it appears, the validator is doing its job and the
prompt needs tightening, not the validator loosening.** Common cause: the model
recomputes a percentage change. Add one line to `SYSTEM` naming that specific
mistake and try again.

- [ ] **Step 9: Break-it-to-prove-it**

Make `compose` return `narrative` unconditionally, rerun. Expected:
`substitutesTheTemplateWhenTheModelInventsAFigure` FAILS. Restore.

In `NarrativeValidator`, change `DECIMAL` to match integers too, rerun.
Expected: `ignoresDatesAndIntegersThatAreNotClaimsAboutMetrics` FAILS. Restore.

- [ ] **Step 10: Commit**

```bash
git add service
git commit -m "feat(agent): Sarvam narrative validated against the findings, template on failure"
```

---

### Task 14: Email delivery through SES sandbox (~0 h 45)

**Files:**
- Create: `service/src/main/java/com/signaldesk/delivery/EmailChannel.java`
- Modify: `service/pom.xml` (AWS SDK v2 SES)
- Test: `service/src/test/java/com/signaldesk/delivery/EmailChannelTest.java`

**Interfaces:**
- Consumes: `SES_FROM`, `SES_TO`, AWS credentials from the default provider chain.
- Produces: `EmailChannel implements Channel` with `name() == "email"`, which
  `Dispatcher` picks up automatically through the `List<Channel>` injection.

**SES is in sandbox and stays there.** Leaving sandbox needs SPF, DKIM and DMARC
in place *before* the request can be filed, and approval runs 4–24 h for
established domains. Delivery to verified team addresses is the real email proof.

- [ ] **Step 1: Add the dependency**

```xml
    <dependency>
      <groupId>software.amazon.awssdk</groupId>
      <artifactId>ses</artifactId>
      <version>2.29.52</version>
    </dependency>
```

Verify it resolves: `./scripts/mvn.sh -q dependency:get -Dartifact=software.amazon.awssdk:ses:2.29.52`.
If it fails, resolve the latest 2.x the same way as Task 12 Step 1 and record it.

- [ ] **Step 2: Write the failing tests**

`service/src/test/java/com/signaldesk/delivery/EmailChannelTest.java`:

```java
package com.signaldesk.delivery;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

class EmailChannelTest {

    @Test
    void reportsNotConfiguredRatherThanThrowingWhenTheEnvironmentIsUnset() {
        DispatchResult r = new EmailChannel("", "", null).send("subject", "body");

        assertThat(r.delivered()).isFalse();
        assertThat(r.detail()).containsIgnoringCase("not configured");
        assertThat(r.channel()).isEqualTo("email");
    }

    @Test
    void parsesACommaSeparatedRecipientList() {
        assertThat(EmailChannel.recipients("a@x.com, b@y.com ,c@z.com"))
                .containsExactly("a@x.com", "b@y.com", "c@z.com");
        assertThat(EmailChannel.recipients("")).isEmpty();
    }

    @Test
    void sendsARealEmailToTheVerifiedAddresses() {
        String from = System.getenv("SES_FROM");
        String to = System.getenv("SES_TO");
        assumeTrue(from != null && !from.isBlank() && to != null && !to.isBlank(),
                "SES_FROM/SES_TO not set");

        DispatchResult r = new EmailChannel(from, to,
                software.amazon.awssdk.services.ses.SesClient.create())
                .send("Signal Desk test", "This is a delivery proof, not a draft.");

        assertThat(r.delivered()).as("SES sandbox delivers only to VERIFIED addresses — "
                + "a 'not verified' error here means Step 0 of the preflight was skipped")
                .isTrue();
    }
}
```

- [ ] **Step 3: Write the channel**

`EmailChannel.java`:

```java
package com.signaldesk.delivery;

import java.util.Arrays;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.ses.SesClient;
import software.amazon.awssdk.services.ses.model.Body;
import software.amazon.awssdk.services.ses.model.Content;
import software.amazon.awssdk.services.ses.model.Destination;
import software.amazon.awssdk.services.ses.model.Message;
import software.amazon.awssdk.services.ses.model.SendEmailRequest;

/** Real delivery, not a draft. Sandbox, to verified addresses only. */
@Component
public class EmailChannel implements Channel {

    private final String from;
    private final String to;
    private final SesClient ses;

    public EmailChannel(@Value("${SES_FROM:}") String from,
                        @Value("${SES_TO:}") String to,
                        SesClient ses) {
        this.from = from;
        this.to = to;
        this.ses = ses;
    }

    static List<String> recipients(String raw) {
        if (raw == null || raw.isBlank()) {
            return List.of();
        }
        return Arrays.stream(raw.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList();
    }

    @Override
    public String name() {
        return "email";
    }

    @Override
    public DispatchResult send(String subject, String body) {
        List<String> addresses = recipients(to);
        if (from.isBlank() || addresses.isEmpty() || ses == null) {
            return new DispatchResult(name(), false, "email not configured (SES_FROM/SES_TO)");
        }
        try {
            var response = ses.sendEmail(SendEmailRequest.builder()
                    .source(from)
                    .destination(Destination.builder().toAddresses(addresses).build())
                    .message(Message.builder()
                            .subject(Content.builder().data(subject).build())
                            .body(Body.builder()
                                    .text(Content.builder().data(body).build())
                                    .build())
                            .build())
                    .build());
            return new DispatchResult(name(), true, "messageId " + response.messageId());
        } catch (RuntimeException e) {
            return new DispatchResult(name(), false,
                    e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }
}
```

Add an `SesClient` bean, tolerant of missing credentials so the app still starts
offline:

```java
package com.signaldesk.delivery;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.services.ses.SesClient;

@Configuration
public class SesConfig {

    @Bean
    public SesClient sesClient() {
        try {
            return SesClient.create();
        } catch (RuntimeException e) {
            return null;   // no credentials: email reports "not configured", app still runs
        }
    }
}
```

- [ ] **Step 4: Run the tests**

Run: `./scripts/mvn.sh -q test -Dtest=EmailChannelTest`
Expected: PASS, with the live test skipped unless `SES_FROM`/`SES_TO` are set.

- [ ] **Step 5: Prove both channels route correctly end to end**

Run the service with `SLACK_WEBHOOK_URL`, `SES_FROM`, `SES_TO` all set. Sweep,
dispatch, then:

```bash
curl -s -X POST "http://localhost:8080/api/dispatch/$RUN" | python3 -m json.tool
```

Expected: a `BREACH` or `CONCERN` audience shows **both** `slack` and `email`
delivered; a `WATCH`-only audience shows Slack alone. Check the inbox.

- [ ] **Step 6: Commit**

```bash
git add service
git commit -m "feat(delivery): SES sandbox email as the second real channel"
```

---

### Task 15: The remaining API surface (~0 h 30)

**Files:**
- Create: `service/src/main/java/com/signaldesk/api/FindingsController.java`, `FeedHealthController.java`
- Create: `service/src/main/java/com/signaldesk/api/dto/FindingDto.java`, `FeedHealthDto.java`
- Modify: `service/src/main/java/com/signaldesk/api/SweepController.java` (CORS for the console)
- Test: `service/src/test/java/com/signaldesk/api/ApiContractTest.java`

**Interfaces:**
- Consumes: `FindingStore`, `GapRegister`, `MetricRegistry`.
- Produces the wire contract the console is written against:
  - `GET /api/runs/{runId}/findings` → `FindingDto[]`, ranked
  - `GET /api/runs/latest/findings` → the same for the most recent run
  - `GET /api/findings/{id}` → one `FindingDto` including `evidenceSql`
  - `GET /api/health/feeds` → `FeedHealthDto[]`
  - `FindingDto` fields: `id, metricId, metricLabel, unit, sliceLabel, tier, cause, observed, gap, confidence, audiences, references[{kind,value,label}], evidenceSql, windowLabel`

DTOs are separate from the domain records deliberately: the console must not be
coupled to `Finding`'s shape, and `evidenceSql` is included on purpose — it is
what the console shows on expand.

- [ ] **Step 1: Write the failing contract test**

`service/src/test/java/com/signaldesk/api/ApiContractTest.java`:

```java
package com.signaldesk.api;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
class ApiContractTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void sweepThenReadTheFindingsBack() throws Exception {
        String body = mvc.perform(post("/api/sweep"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runId").exists())
                .andExpect(jsonPath("$.findingCount").exists())
                .andReturn().getResponse().getContentAsString();
        String runId = body.replaceAll(".*\"runId\":\"([^\"]*)\".*", "$1");

        mvc.perform(get("/api/runs/" + runId + "/findings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").exists())
                .andExpect(jsonPath("$[0].metricLabel").exists())
                .andExpect(jsonPath("$[0].tier").exists())
                .andExpect(jsonPath("$[0].evidenceSql").exists())
                .andExpect(jsonPath("$[0].references").isArray());
    }

    @Test
    void latestIsAnAliasSoTheConsoleOpensOnACompletedSweep() throws Exception {
        mvc.perform(post("/api/sweep")).andExpect(status().isOk());

        mvc.perform(get("/api/runs/latest/findings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").exists());
    }

    @Test
    void oneFindingCarriesItsEvidence() throws Exception {
        mvc.perform(post("/api/sweep"));
        String findings = mvc.perform(get("/api/runs/latest/findings"))
                .andReturn().getResponse().getContentAsString();
        String id = findings.replaceAll(".*?\"id\":\"([^\"]*)\".*", "$1");

        mvc.perform(get("/api/findings/" + id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.evidenceSql").exists());
    }

    @Test
    void anUnknownRunIsFourOhFourNotAnEmptyList() throws Exception {
        mvc.perform(get("/api/runs/run-does-not-exist/findings"))
                .andExpect(status().isNotFound());
    }

    @Test
    void feedHealthIsAFirstClassSurface() throws Exception {
        mvc.perform(get("/api/health/feeds"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].feed").exists())
                .andExpect(jsonPath("$[0].rowsRejected").exists())
                .andExpect(jsonPath("$[0].confidence").exists());
    }
}
```

- [ ] **Step 2: Run to verify failure**

Run: `./scripts/mvn.sh -q test -Dtest=ApiContractTest`
Expected: FAIL — 404 on the findings routes.

- [ ] **Step 3: Write the DTOs**

`service/src/main/java/com/signaldesk/api/dto/FindingDto.java`:

```java
package com.signaldesk.api.dto;

import com.signaldesk.registry.Metric;
import com.signaldesk.verdict.Finding;
import java.util.List;

public record FindingDto(
        String id, String metricId, String metricLabel, String unit, String sliceLabel,
        String tier, String cause, double observed, double gap, double confidence,
        List<String> audiences, List<ReferenceDto> references,
        String evidenceSql, String windowLabel) {

    public record ReferenceDto(String kind, double value, String label) {}

    public static FindingDto from(Finding f, Metric m) {
        return new FindingDto(f.id(), f.metricId(), m.label(), m.unit(), f.slice().label(),
                f.tier().name(), f.cause().name(), f.observed(), f.gap(), f.confidence(),
                f.audiences().stream().map(Enum::name).sorted().toList(),
                f.refs().stream()
                        .map(r -> new ReferenceDto(r.kind().name(), r.value(), r.label()))
                        .toList(),
                f.evidenceSql(), f.window().label());
    }
}
```

`FeedHealthDto.java`:

```java
package com.signaldesk.api.dto;

import com.signaldesk.ingest.FeedHealth;

public record FeedHealthDto(String feed, long rowsLoaded, long rowsRejected,
                            long unmatchedKeys, long nullCriticalFields,
                            double confidence, boolean mustBeDisclosed) {

    public static FeedHealthDto from(FeedHealth h) {
        return new FeedHealthDto(h.feed().name(), h.rowsLoaded(), h.rowsRejected(),
                h.unmatchedKeys(), h.nullCriticalFields(), h.confidence(), h.mustBeDisclosed());
    }
}
```

- [ ] **Step 4: Write the controllers**

`FindingsController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.agent.FindingStore;
import com.signaldesk.agent.SweepRun;
import com.signaldesk.api.dto.FindingDto;
import com.signaldesk.registry.MetricRegistry;
import java.util.List;
import java.util.Optional;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@CrossOrigin
public class FindingsController {

    private final FindingStore store;
    private final MetricRegistry registry;

    public FindingsController(FindingStore store, MetricRegistry registry) {
        this.store = store;
        this.registry = registry;
    }

    @GetMapping("/runs/{runId}/findings")
    public ResponseEntity<List<FindingDto>> findings(@PathVariable String runId) {
        Optional<SweepRun> run = "latest".equals(runId) ? store.latest() : store.get(runId);
        return run
                .map(r -> ResponseEntity.ok(r.findings().stream()
                        .map(f -> FindingDto.from(f, registry.byId(f.metricId())))
                        .toList()))
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping("/findings/{id}")
    public ResponseEntity<FindingDto> finding(@PathVariable String id) {
        return store.finding(id)
                .map(f -> ResponseEntity.ok(FindingDto.from(f, registry.byId(f.metricId()))))
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
```

`FeedHealthController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.api.dto.FeedHealthDto;
import com.signaldesk.ingest.GapRegister;
import java.util.List;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@CrossOrigin
public class FeedHealthController {

    private final GapRegister gaps;

    public FeedHealthController(GapRegister gaps) {
        this.gaps = gaps;
    }

    /** A quarantined row is a finding, not a log line — so it gets an endpoint. */
    @GetMapping("/health/feeds")
    public List<FeedHealthDto> feeds() {
        return gaps.assess().values().stream().map(FeedHealthDto::from).toList();
    }
}
```

Add `@CrossOrigin` to `SweepController` and `DispatchController` too — the
console runs on a different port in development, and stateless with no auth
(spec §2.2) means a permissive CORS policy costs nothing.

- [ ] **Step 5: Run the contract test, then everything**

Run: `./scripts/mvn.sh -q test -Dtest=ApiContractTest`
Expected: PASS, 5 tests.

Run: `./scripts/mvn.sh -q test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add service
git commit -m "feat(api): findings, finding detail and feed-health endpoints for the console"
```

---

### Task 16: Containerise the service and deploy it to Render (~0 h 50)

**Files:**
- Create: `Dockerfile` (repo root — the build context needs both `service/` and `data/`)
- Create: `.dockerignore`
- Create: `render.yaml`
- Create: `service/src/main/java/com/signaldesk/api/HealthController.java`
- Modify: `service/src/main/resources/application.yaml` (`PORT`, configurable CORS origins)
- Modify: `service/src/main/java/com/signaldesk/api/*Controller.java` (replace bare `@CrossOrigin`)
- Create: `service/src/main/java/com/signaldesk/api/CorsConfig.java`
- Test: `service/src/test/java/com/signaldesk/api/HealthControllerTest.java`
- Test: `service/src/test/java/com/signaldesk/api/CorsConfigTest.java`

**Interfaces:**
- Consumes: everything through Task 15.
- Produces:
  - `GET /api/health` → `{"status":"ok","activeMetrics":n,"clock":"fixture|system"}` — Render's health check target, distinct from `/api/health/feeds`
  - `signaldesk.cors.origins` config property, comma-separated
  - A runnable image, and a deployed base URL Task 19 points the console at

**Why now and not in the deck task.** Criterion 3 (20%) asks for "deployable into
an existing platform", spec §11 names the venues, and `PROPOSAL.md` promises a
judge that the repository seam makes the production story an adapter swap. A
deploy first attempted at hour sixteen fails at hour sixteen. Deploying here also
surfaces the console's API-base problem — the Vite dev proxy does not exist in
production — while there is still time to fix it.

**Both surfaces go on Render**, not the spec's Render/Vercel split — see Task 19's
opening note for the reasoning and what it costs. This task's blueprint describes
the service; Task 19 appends the console to the same file.

**What this task does not change.** The scored demo still runs on the laptop.
Render's free tier spins down after 15 minutes idle and a JVM cold start is 30–90
seconds, so the deployed URL is the deployability *evidence*, not the demo. Spec
§11 is explicit about this and it is not a hedge — it is the right call.

- [ ] **Step 1: Write the failing health-endpoint test**

`service/src/test/java/com/signaldesk/api/HealthControllerTest.java`:

```java
package com.signaldesk.api;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
class HealthControllerTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void reportsReadyOnlyOnceTheFixtureIsLoadedAndMetricsAreActive() throws Exception {
        mvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.activeMetrics").exists())
                .andExpect(jsonPath("$.clock").exists());
    }

    @Test
    void doesNotCollideWithTheFeedHealthEndpoint() throws Exception {
        // /api/health and /api/health/feeds are different resources and both must
        // resolve. A greedy mapping on one silently shadows the other.
        mvc.perform(get("/api/health")).andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"));
        mvc.perform(get("/api/health/feeds")).andExpect(status().isOk())
                .andExpect(jsonPath("$[0].feed").exists());
    }
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./scripts/mvn.sh -q test -Dtest=HealthControllerTest`
Expected: FAIL — 404 on `/api/health`.

- [ ] **Step 3: Write the health controller**

`service/src/main/java/com/signaldesk/api/HealthController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.registry.MetricRegistry;
import java.time.Clock;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Render's health check target. Deliberately reports something real: a service
 * that booted but loaded no metrics is not healthy, and a 200 that means nothing
 * is how a broken deploy stays green.
 */
@RestController
@RequestMapping("/api")
public class HealthController {

    private final MetricRegistry registry;
    private final String clockMode;

    public HealthController(MetricRegistry registry,
                            @Value("${signaldesk.clock:fixture}") String clockMode) {
        this.registry = registry;
        this.clockMode = clockMode;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", registry.active().isEmpty() ? "degraded" : "ok",
                "activeMetrics", registry.active().size(),
                "clock", clockMode);
    }
}
```

- [ ] **Step 4: Make the port and CORS origins configurable**

Render injects `PORT` and expects the process to bind it. A hardcoded 8080 deploys
and then fails its health check with no obvious cause.

In `application.yaml`:

```yaml
server:
  port: ${PORT:8080}
signaldesk:
  cors:
    origins: "http://localhost:5173"
```

`service/src/main/java/com/signaldesk/api/CorsConfig.java`:

```java
package com.signaldesk.api;

import java.util.Arrays;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * One place, configurable per environment. The bare @CrossOrigin annotations this
 * replaces allowed every origin — acceptable for a stateless no-auth service on a
 * laptop, sloppy on a public URL, and impossible to point at the deployed
 * console's origin without a redeploy.
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    private final List<String> origins;

    public CorsConfig(@Value("${signaldesk.cors.origins}") String origins) {
        this.origins = Arrays.stream(origins.split(","))
                .map(String::trim).filter(s -> !s.isEmpty()).toList();
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOriginPatterns(origins.toArray(String[]::new))
                .allowedMethods("GET", "POST")
                .allowedHeaders("Content-Type");
    }
}
```

Remove `@CrossOrigin` from `FindingsController`, `FeedHealthController`,
`SweepController`, `DispatchController`, `BriefController`, and `AskController`
once it exists — a class-level annotation overrides the global registry and would
silently defeat this config.

- [ ] **Step 5: Write the CORS test**

`service/src/test/java/com/signaldesk/api/CorsConfigTest.java`:

```java
package com.signaldesk.api;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = "signaldesk.cors.origins=https://signal-desk-console.onrender.com")
class CorsConfigTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void allowsTheConfiguredConsoleOrigin() throws Exception {
        mvc.perform(options("/api/runs/latest/findings")
                        .header("Origin", "https://signal-desk-console.onrender.com")
                        .header("Access-Control-Request-Method", "GET"))
                .andExpect(status().isOk())
                .andExpect(header().string("Access-Control-Allow-Origin",
                        "https://signal-desk-console.onrender.com"));
    }

    @Test
    void refusesAnOriginThatIsNotConfigured() throws Exception {
        mvc.perform(options("/api/runs/latest/findings")
                        .header("Origin", "https://not-our-console.example.com")
                        .header("Access-Control-Request-Method", "GET"))
                .andExpect(status().isForbidden());
    }
}
```

The second test is the one that matters. With a bare `@CrossOrigin` left anywhere
on these controllers it passes nothing and fails here — which is exactly the
regression Step 4 warns about.

- [ ] **Step 6: Write the Dockerfile**

At the **repo root**, because the image needs both `service/` and `data/fixture`
and a build context cannot reach above itself.

`Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1

# ---- build ----
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build

# Dependencies first, so a source-only change does not re-download the world.
COPY service/pom.xml service/pom.xml
RUN mvn -f service/pom.xml -B -q dependency:go-offline

COPY service/src service/src
RUN mvn -f service/pom.xml -B -q -DskipTests package

# ---- runtime ----
FROM eclipse-temurin:21-jre
WORKDIR /app

# The trip logs are read-only, so they are baked in: no persistent disk, no AWS
# spend, and the container has no external data dependency at all.
COPY data/fixture /app/data/fixture
COPY --from=build /build/service/target/*.jar /app/app.jar

# JDK 21 is what the toolchain is pinned to; a JRE mismatch here would be a
# different runtime than every test ran against.
RUN java -version

ENV JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseSerialGC"
EXPOSE 8080

# The fixture path is passed explicitly rather than through an environment
# variable: Spring's relaxed binding maps signaldesk.fixture-dir to
# SIGNALDESK_FIXTUREDIR, which is easy to get wrong and silent when you do.
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar \
  --signaldesk.fixture-dir=/app/data/fixture"]
```

`.dockerignore`:

```
.git
.gitignore
.superpowers
.worktrees
node_modules
console/node_modules
console/dist
commute-os
service/target
docs
*.md
*.pdf
*.zip
.DS_Store
.env
.env.local
.mcp.json
```

Excluding `.env`-shaped files from the build context is not cosmetic: anything in
the context can end up in a layer, and a Slack webhook URL is a credential.

- [ ] **Step 7: Build and run the image locally, and prove the loop works inside it**

Run:
```bash
docker build -t signal-desk:local .
docker run --rm -p 8081:8080 -e PORT=8080 --name signal-desk-test -d signal-desk:local
sleep 45   # JVM cold start
curl -s http://localhost:8081/api/health
curl -s -X POST http://localhost:8081/api/sweep
curl -s http://localhost:8081/api/health/feeds | head -c 400
docker logs signal-desk-test | grep -i sweep
docker stop signal-desk-test
```

Expected: health reports `"status":"ok"` with a non-zero `activeMetrics`; the
sweep returns a runId and a non-zero finding count; feed health shows a non-zero
quarantined count; and the logs show the startup sweep firing **with no prompt,
inside a container** — which is the deployability claim made concrete.

If the sweep returns zero findings, the fixture did not make it into the image or
the simulated clock is not pinned to it. Check `docker run --rm signal-desk:local
ls /app/data/fixture` before touching anything else.

- [ ] **Step 8: Write the Render blueprint**

`render.yaml`:

```yaml
services:
  - type: web
    name: signal-desk-service
    runtime: docker
    dockerfilePath: ./Dockerfile
    dockerContext: .
    plan: free
    healthCheckPath: /api/health
    autoDeploy: false
    envVars:
      # sync: false means Render prompts for the value and never stores it in git.
      - key: SARVAM_API_KEY
        sync: false
      - key: SLACK_WEBHOOK_URL
        sync: false
      - key: SES_FROM
        sync: false
      - key: SES_TO
        sync: false
      - key: AWS_ACCESS_KEY_ID
        sync: false
      - key: AWS_SECRET_ACCESS_KEY
        sync: false
      - key: AWS_REGION
        value: ap-south-1
      - key: SIGNALDESK_CORS_ORIGINS
        sync: false      # set to the console's Render URL in Task 19
```

`autoDeploy: false` is deliberate: a push mid-build must not replace a warmed
instance minutes before presenting.

- [ ] **Step 9: Deploy it**

Create the service from the blueprint (Render dashboard → New → Blueprint, point
at the repo), set the four `sync: false` secrets in the Render UI — **never in
`render.yaml`, never in a commit** — and trigger the first deploy.

Then verify against the real URL:

```bash
BASE=https://<your-service>.onrender.com
curl -s "$BASE/api/health"
curl -s -X POST "$BASE/api/sweep"
curl -s "$BASE/api/runs/latest/findings" | head -c 400
```

Expected: the same three answers as Step 7. **Record the base URL** — Task 19
needs it, and so does the deck.

First request after a spin-down takes 30–90 seconds. That is expected and is why
the demo does not depend on it.

- [ ] **Step 10: Confirm no secret reached the repo**

Run:
```bash
git grep -nE 'onrender\.com|hooks\.slack\.com/services/[A-Z0-9]{5,}|AKIA[0-9A-Z]{16}' -- . ':!*.md' || echo "clean"
grep -c 'sync: false' render.yaml
```
Expected: `clean` from the first command (the deployed hostname belongs in the
deck and the README, not in code), and six `sync: false` entries.

- [ ] **Step 11: Run the whole suite**

Run: `./scripts/mvn.sh -q test`
Expected: PASS. `CorsConfigTest` is the new gate; if `refusesAnOriginThatIsNotConfigured`
fails, a `@CrossOrigin` annotation survived Step 4.

- [ ] **Step 12: Break-it-to-prove-it**

Set `server.port: 8080` (dropping `${PORT:8080}`), rebuild the image, and run it
with `-e PORT=9999 -p 8081:9999`. Expected: the container is unreachable — the
exact failure mode a Render health check reports as a deploy that never came up.
Restore.

Re-add `@CrossOrigin` to `FindingsController`, rerun `CorsConfigTest`. Expected:
`refusesAnOriginThatIsNotConfigured` FAILS. Restore.

- [ ] **Step 13: Commit**

```bash
git add Dockerfile .dockerignore render.yaml service
git commit -m "feat(deploy): containerise the service, real health check, configurable CORS, Render blueprint"
```

---

### Task 17: Console — ranked findings, expandable to the evidence (~1 h 15)

**Files:**
- Create: `console/package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`
- Create: `console/src/main.tsx`, `App.tsx`, `api/types.ts`, `api/client.ts`
- Create: `console/src/components/TierBadge.tsx`, `FindingRow.tsx`, `EvidencePanel.tsx`, `FindingsList.tsx`
- Test: `console/src/components/__tests__/FindingsList.test.tsx`, `FindingRow.test.tsx`

**Interfaces:**
- Consumes: `GET /api/runs/latest/findings`, `GET /api/findings/{id}`.
- Produces: `types.ts` mirroring `FindingDto` exactly; `fetchLatestFindings()`,
  `fetchFinding(id)`, `triggerSweep()`, `fetchFeedHealth()`, `dispatchRun(runId)`
  — Task 18 and Task 23 import from here.

**Severity is encoded in form as well as colour** — a stripe and a text label,
not colour alone. That is an accessibility requirement, and it also survives a
projector that washes out red.

- [ ] **Step 1: Scaffold and wire the Node guard**

Run:
```bash
nvm use
npm create vite@latest console -- --template react-ts
cd console && npm install
npm install recharts
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

Add to `console/package.json`:

```json
  "engines": { "node": ">=22.12" },
  "scripts": {
    "predev": "node ../scripts/require-node.mjs",
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run"
  }
```

`engine-strict=true` in the root `.npmrc` gates `npm install`; `predev` gates
`npm run dev`, because `engine-strict` does nothing for `run`.

Add to `vite.config.ts`:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8080' } },
  test: { environment: 'jsdom', globals: true },
})
```

Verify: `node -v` reports v22.x, `npm run predev` exits 0, `npm run dev` serves.

- [ ] **Step 2: Write the failing component test**

`console/src/components/__tests__/FindingsList.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FindingsList } from '../FindingsList'
import type { Finding } from '../../api/types'

const finding = (over: Partial<Finding> = {}): Finding => ({
  id: 'f1',
  metricId: 'vendor_ota',
  metricLabel: 'Vendor on-time share',
  unit: '%',
  sliceLabel: 'vendor V07',
  tier: 'BREACH',
  cause: 'PEER_LAGGARD',
  observed: 61.4,
  gap: 27.8,
  confidence: 0.97,
  audiences: ['FACILITIES_HEAD'],
  references: [{ kind: 'PEER', value: 89.2, label: 'peer median' }],
  evidenceSql: 'SELECT 100.0 * sum(...) FROM trips t WHERE ...',
  windowLabel: '2026-08-29..2026-09-04',
  ...over,
})

describe('FindingsList', () => {
  it('renders findings in the order the server ranked them', () => {
    render(<FindingsList findings={[
      finding({ id: 'a', tier: 'BREACH', sliceLabel: 'vendor V07' }),
      finding({ id: 'b', tier: 'WATCH', sliceLabel: 'site SITE2' }),
    ]} />)

    const rows = screen.getAllByRole('button', { name: /vendor|site/ })
    expect(rows[0]).toHaveTextContent('vendor V07')
    expect(rows[1]).toHaveTextContent('site SITE2')
  })

  it('encodes severity as a text label, not colour alone', () => {
    render(<FindingsList findings={[finding()]} />)

    expect(screen.getByText('BREACH')).toBeInTheDocument()
  })

  it('shows every reference point, because a metric without context is just a number', () => {
    render(<FindingsList findings={[finding({
      references: [
        { kind: 'TREND', value: 84.1, label: '4-week average' },
        { kind: 'PEER', value: 89.2, label: 'peer median' },
      ],
    })]} />)

    expect(screen.getByText(/4-week average/)).toBeInTheDocument()
    expect(screen.getByText(/peer median/)).toBeInTheDocument()
  })

  it('discloses confidence only when it is below 0.9', () => {
    const { rerender } = render(<FindingsList findings={[finding({ confidence: 0.62 })]} />)
    expect(screen.getByText(/62%/)).toBeInTheDocument()

    rerender(<FindingsList findings={[finding({ confidence: 0.97 })]} />)
    expect(screen.queryByText(/97%/)).not.toBeInTheDocument()
  })

  it('says so plainly when a sweep found nothing', () => {
    render(<FindingsList findings={[]} />)

    expect(screen.getByText(/no findings/i)).toBeInTheDocument()
  })
})
```

`console/src/components/__tests__/FindingRow.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { FindingRow } from '../FindingRow'
import type { Finding } from '../../api/types'

const f: Finding = {
  id: 'f1', metricId: 'ota', metricLabel: 'On-time arrival', unit: '%',
  sliceLabel: 'overall', tier: 'CONCERN', cause: 'BELOW_TARGET',
  observed: 78, gap: 12, confidence: 0.97, audiences: ['TRANSPORT_MANAGER'],
  references: [{ kind: 'TARGET', value: 90, label: 'SLA target' }],
  evidenceSql: 'SELECT 100.0 * sum(CASE WHEN t.actual_at <= t.scheduled_at + 300000 ...',
  windowLabel: '2026-08-29..2026-09-04',
}

describe('FindingRow', () => {
  it('hides the evidence until asked, then shows the exact query', async () => {
    render(<FindingRow finding={f} />)
    expect(screen.queryByText(/SELECT 100.0/)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /On-time arrival/ }))

    expect(screen.getByText(/SELECT 100.0/)).toBeInTheDocument()
  })

  it('names the rule that fired alongside the number', async () => {
    render(<FindingRow finding={f} />)
    await userEvent.click(screen.getByRole('button', { name: /On-time arrival/ }))

    expect(screen.getByText(/BELOW_TARGET|below the declared target/i)).toBeInTheDocument()
  })
})
```

Install `@testing-library/user-event` as a dev dependency.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd console && npm test`
Expected: FAIL — `Failed to resolve import "../FindingsList"`.

- [ ] **Step 4: Write the types and the client**

`console/src/api/types.ts`:

```ts
export type Tier = 'PASS' | 'WATCH' | 'CONCERN' | 'BREACH'

export interface Reference {
  kind: 'TREND' | 'TARGET' | 'PEER'
  value: number
  label: string
}

export interface Finding {
  id: string
  metricId: string
  metricLabel: string
  unit: string
  sliceLabel: string
  tier: Tier
  cause: string
  observed: number
  gap: number
  confidence: number
  audiences: string[]
  references: Reference[]
  evidenceSql: string
  windowLabel: string
}

export interface FeedHealth {
  feed: string
  rowsLoaded: number
  rowsRejected: number
  unmatchedKeys: number
  nullCriticalFields: number
  confidence: number
  mustBeDisclosed: boolean
}

export interface SweepResponse {
  runId: string
  findingCount: number
}

export interface DispatchResult {
  channel: string
  delivered: boolean
  detail: string
}
```

`console/src/api/client.ts`:

```ts
import type { DispatchResult, FeedHealth, Finding, SweepResponse } from './types'

const base = import.meta.env.VITE_API_BASE ?? ''

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, init)
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const fetchLatestFindings = () => json<Finding[]>('/api/runs/latest/findings')
export const fetchFinding = (id: string) => json<Finding>(`/api/findings/${id}`)
export const fetchFeedHealth = () => json<FeedHealth[]>('/api/health/feeds')
export const triggerSweep = () => json<SweepResponse>('/api/sweep', { method: 'POST' })
export const dispatchRun = (runId: string) =>
  json<DispatchResult[]>(`/api/dispatch/${runId}`, { method: 'POST' })
```

- [ ] **Step 5: Write the components**

`console/src/components/TierBadge.tsx`:

```tsx
import type { Tier } from '../api/types'

const STRIPE: Record<Tier, string> = {
  BREACH: '#b3261e',
  CONCERN: '#a15c00',
  WATCH: '#5b5bd6',
  PASS: '#1e7a45',
}

/** Severity in form as well as colour: a stripe AND the word. */
export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span
        aria-hidden
        style={{ width: 4, height: 16, background: STRIPE[tier], borderRadius: 2 }}
      />
      <strong style={{ fontSize: 12, letterSpacing: 0.5 }}>{tier}</strong>
    </span>
  )
}
```

`console/src/components/EvidencePanel.tsx`:

```tsx
import type { Finding } from '../api/types'

/**
 * The answer to "where did this number come from" is a query the reader can run,
 * not a claim. This is why evidenceSql travels on every finding.
 */
export function EvidencePanel({ finding }: { finding: Finding }) {
  return (
    <div style={{ padding: '8px 12px', background: '#f6f6f7', fontSize: 13 }}>
      <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', margin: 0 }}>
        <dt>Observed</dt>
        <dd>{finding.observed.toFixed(2)}{finding.unit === '%' ? '%' : ` ${finding.unit}`}</dd>
        {finding.references.map((r) => (
          <>
            <dt key={`${r.kind}-t`}>{r.label}</dt>
            <dd key={`${r.kind}-d`}>{r.value.toFixed(2)}</dd>
          </>
        ))}
        <dt>Rule that fired</dt>
        <dd>{finding.cause}</dd>
        <dt>Confidence</dt>
        <dd>{(finding.confidence * 100).toFixed(0)}%</dd>
        <dt>Sent to</dt>
        <dd>{finding.audiences.join(', ')}</dd>
      </dl>
      <pre style={{ overflowX: 'auto', marginTop: 8, fontSize: 12, whiteSpace: 'pre-wrap' }}>
        {finding.evidenceSql}
      </pre>
    </div>
  )
}
```

`console/src/components/FindingRow.tsx`:

```tsx
import { useState } from 'react'
import type { Finding } from '../api/types'
import { EvidencePanel } from './EvidencePanel'
import { TierBadge } from './TierBadge'

export function FindingRow({ finding }: { finding: Finding }) {
  const [open, setOpen] = useState(false)
  return (
    <li style={{ borderBottom: '1px solid #e4e4e7', listStyle: 'none' }}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{
          width: '100%', display: 'flex', gap: 12, alignItems: 'baseline',
          padding: '10px 12px', background: 'none', border: 'none',
          textAlign: 'left', cursor: 'pointer', font: 'inherit',
        }}
      >
        <TierBadge tier={finding.tier} />
        <span style={{ fontWeight: 600 }}>{finding.metricLabel}</span>
        <span style={{ color: '#52525b' }}>{finding.sliceLabel}</span>
        <span style={{ marginLeft: 'auto' }}>
          {finding.observed.toFixed(2)}{finding.unit === '%' ? '%' : ''}
        </span>
        <span style={{ color: '#52525b', fontSize: 13 }}>
          {finding.references.map((r) => `${r.label} ${r.value.toFixed(2)}`).join(' · ')}
        </span>
        {finding.confidence < 0.9 && (
          <span style={{ color: '#a15c00', fontSize: 12 }}>
            confidence {(finding.confidence * 100).toFixed(0)}%
          </span>
        )}
      </button>
      {open && <EvidencePanel finding={finding} />}
    </li>
  )
}
```

`console/src/components/FindingsList.tsx`:

```tsx
import type { Finding } from '../api/types'
import { FindingRow } from './FindingRow'

export function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <p style={{ padding: 12, color: '#52525b' }}>No findings in this window.</p>
  }
  return (
    <ul style={{ margin: 0, padding: 0 }}>
      {findings.map((f) => (
        <FindingRow key={f.id} finding={f} />
      ))}
    </ul>
  )
}
```

`console/src/App.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { fetchLatestFindings, triggerSweep } from './api/client'
import { FindingsList } from './components/FindingsList'
import type { Finding } from './api/types'

export default function App() {
  const [findings, setFindings] = useState<Finding[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = () => fetchLatestFindings().then(setFindings).catch((e) => setError(String(e)))

  // The console opens on a completed sweep, not an empty shell: the service has
  // already swept on startup, with no prompt.
  useEffect(() => { load() }, [])

  return (
    <main style={{ maxWidth: 1000, margin: '0 auto', padding: 16, font: '14px system-ui' }}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Signal Desk</h1>
        <button onClick={() => triggerSweep().then(load)}>Sweep now</button>
      </header>
      {error && <p style={{ color: '#b3261e' }}>{error}</p>}
      <h2 style={{ fontSize: 15, marginTop: 20 }}>Findings, ranked</h2>
      <FindingsList findings={findings} />
    </main>
  )
}
```

- [ ] **Step 6: Run the console tests**

Run: `cd console && npm test`
Expected: PASS, 7 tests.

- [ ] **Step 7: See it against the real service**

Run the service, then `cd console && npm run dev`, open `http://localhost:5173`.
Expected: a ranked list that opens **already populated**, each row expanding to
the references, the rule, the confidence and the SQL.

- [ ] **Step 8: Break-it-to-prove-it**

Delete the `{finding.confidence < 0.9 && ...}` guard so confidence always shows,
rerun. Expected: `discloses confidence only when it is below 0.9` FAILS. Restore.

Remove `<strong>{tier}</strong>` from `TierBadge` so only the colour stripe
remains, rerun. Expected: `encodes severity as a text label, not colour alone`
FAILS. Restore.

- [ ] **Step 9: Commit**

```bash
git add console
git commit -m "feat(console): ranked findings expandable to references, rule and evidence SQL"
```

---

### Task 18: Console — feed health and the brief preview (~0 h 45)

**Files:**
- Create: `console/src/components/FeedHealthStrip.tsx`, `BriefPreview.tsx`
- Create: `service/src/main/java/com/signaldesk/api/BriefController.java`
- Test: `console/src/components/__tests__/FeedHealthStrip.test.tsx`

**Interfaces:**
- Consumes: `fetchFeedHealth()`, `dispatchRun(runId)`.
- Produces: `GET /api/runs/{runId}/brief?audience=FACILITIES_HEAD` → `{ "audience": "...", "brief": "..." }`.

**A quarantined row is a finding, not a log line** — so the strip shows the
rejected count as a number, not as an absence.

- [ ] **Step 1: Write the failing test**

`console/src/components/__tests__/FeedHealthStrip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FeedHealthStrip } from '../FeedHealthStrip'
import type { FeedHealth } from '../../api/types'

const feed = (over: Partial<FeedHealth> = {}): FeedHealth => ({
  feed: 'TRIPS', rowsLoaded: 8000, rowsRejected: 120, unmatchedKeys: 0,
  nullCriticalFields: 160, confidence: 0.965, mustBeDisclosed: false, ...over,
})

describe('FeedHealthStrip', () => {
  it('shows quarantined rows as a number rather than hiding them', () => {
    render(<FeedHealthStrip feeds={[feed()]} />)

    expect(screen.getByText('120')).toBeInTheDocument()
  })

  it('flags a feed whose confidence is below 0.9', () => {
    render(<FeedHealthStrip feeds={[
      feed({ feed: 'FEEDBACK', confidence: 0.42, mustBeDisclosed: true }),
    ]} />)

    expect(screen.getByText(/42%/)).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /FEEDBACK/ })).toHaveAttribute('data-disclose', 'true')
  })

  it('renders every feed, so a missing one is visible as an absence', () => {
    render(<FeedHealthStrip feeds={[feed({ feed: 'TRIPS' }), feed({ feed: 'COSTS' })]} />)

    expect(screen.getAllByRole('row')).toHaveLength(3)   // header + two feeds
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd console && npm test -- FeedHealthStrip`
Expected: FAIL — unresolved import.

- [ ] **Step 3: Write the components**

`console/src/components/FeedHealthStrip.tsx`:

```tsx
import type { FeedHealth } from '../api/types'

export function FeedHealthStrip({ feeds }: { feeds: FeedHealth[] }) {
  return (
    <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
      <thead>
        <tr>
          <th style={{ textAlign: 'left' }}>Feed</th>
          <th style={{ textAlign: 'right' }}>Loaded</th>
          <th style={{ textAlign: 'right' }}>Quarantined</th>
          <th style={{ textAlign: 'right' }}>Unmatched</th>
          <th style={{ textAlign: 'right' }}>Confidence</th>
        </tr>
      </thead>
      <tbody>
        {feeds.map((f) => (
          <tr key={f.feed} data-disclose={String(f.mustBeDisclosed)}
              style={{ borderTop: '1px solid #e4e4e7' }}>
            <td>{f.feed}</td>
            <td style={{ textAlign: 'right' }}>{f.rowsLoaded}</td>
            <td style={{ textAlign: 'right', color: f.rowsRejected > 0 ? '#a15c00' : undefined }}>
              {f.rowsRejected}
            </td>
            <td style={{ textAlign: 'right' }}>{f.unmatchedKeys}</td>
            <td style={{ textAlign: 'right', fontWeight: f.mustBeDisclosed ? 700 : 400 }}>
              {(f.confidence * 100).toFixed(0)}%
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
```

`console/src/components/BriefPreview.tsx`:

```tsx
import { useState } from 'react'
import { dispatchRun } from '../api/client'
import type { DispatchResult } from '../api/types'

export function BriefPreview({ runId, brief }: { runId: string; brief: string }) {
  const [results, setResults] = useState<DispatchResult[] | null>(null)
  const [sending, setSending] = useState(false)

  const send = async () => {
    setSending(true)
    try {
      setResults(await dispatchRun(runId))
    } finally {
      setSending(false)
    }
  }

  return (
    <section>
      <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f7', padding: 12, fontSize: 13 }}>
        {brief}
      </pre>
      <button onClick={send} disabled={sending}>
        {sending ? 'Sending…' : 'Send this brief'}
      </button>
      {results && (
        <ul style={{ fontSize: 13 }}>
          {results.map((r, i) => (
            <li key={i}>
              {r.channel}: {r.delivered ? 'delivered' : `failed — ${r.detail}`}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
```

`BriefController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.agent.Composer;
import com.signaldesk.agent.FindingStore;
import com.signaldesk.verdict.Audience;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@CrossOrigin
public class BriefController {

    private final Composer composer;
    private final FindingStore store;

    public BriefController(Composer composer, FindingStore store) {
        this.composer = composer;
        this.store = store;
    }

    @GetMapping("/runs/{runId}/brief")
    public ResponseEntity<Map<String, String>> brief(
            @PathVariable String runId,
            @RequestParam(defaultValue = "TRANSPORT_MANAGER") String audience) {
        Audience who = Audience.valueOf(audience);
        var run = "latest".equals(runId) ? store.latest() : store.get(runId);
        return run
                .map(r -> ResponseEntity.ok(Map.of(
                        "audience", who.name(),
                        "runId", r.runId(),
                        "brief", composer.compose(r, who))))
                .orElseGet(() -> ResponseEntity.notFound().build());
    }
}
```

Add `fetchBrief` to `client.ts`:

```ts
export const fetchBrief = (runId: string, audience: string) =>
  json<{ audience: string; runId: string; brief: string }>(
    `/api/runs/${runId}/brief?audience=${audience}`,
  )
```

- [ ] **Step 4: Wire both into `App.tsx`**

Add a feed-health section above the findings and a brief section below, loading
`fetchFeedHealth()` and `fetchBrief('latest', 'FACILITIES_HEAD')` in the same
`useEffect` as the findings, storing `runId` from the brief response so the
dispatch button has one.

- [ ] **Step 5: Run the tests and look at it**

Run: `cd console && npm test`
Expected: PASS, 10 tests.

Open the console with the service running. Expected: feed health at the top with
a non-zero quarantined count, findings in the middle, the brief at the bottom
with a working send button.

- [ ] **Step 6: Commit**

```bash
git add console service
git commit -m "feat(console): feed-health strip and brief preview with a real dispatch button"
```

---

### Task 19: Deploy the console to Render as a static site and prove the deployed pair (~0 h 40)

**Files:**
- Modify: `render.yaml` (add the static site alongside the Docker service from Task 16)
- Create: `console/.env.production.example`
- Create: `console/src/api/__tests__/client.test.ts`
- Modify: `console/src/api/client.ts` (trim a trailing slash from the base — see Step 1)
- Modify: `console/src/App.tsx` (surface which API the console is talking to)
- Modify: `README.md` (record both deployed URLs)

**Interfaces:**
- Consumes: the Render service URL from Task 16, `VITE_API_BASE`.
- Produces: a deployed console URL, which goes into the service's
  `SIGNALDESK_CORS_ORIGINS` — the two services are mutually dependent, so the
  order of the steps below matters.

**Both surfaces live on Render — this is a deliberate departure from spec §11.**
The spec puts the console on Vercel because Vercel has no Java runtime and cannot
take the service. That reasoning is still sound, but it is not the only option:
Render also serves static sites free, so one provider can host both. The human
partner chose Render for both. What that buys:

- one dashboard, one blueprint, one set of credentials — during a timed build,
  fewer places to be wrong
- both services described in the same `render.yaml`, so the deployment story is
  one file a judge can read
- no second CLI login (`npx vercel`) in the critical path

What it costs: Render's free static tier is a CDN like any other, so nothing
technical. The deck must say **Render** for both — spec §11's Vercel wording is
superseded and repeating it on stage would be wrong.

`client.ts` was written deployment-ready in Task 17 (`import.meta.env.VITE_API_BASE
?? ''`), so almost no production code changes are needed to reach the API. What is
missing is the build configuration, the SPA rewrite, the CORS handshake, and proof
that the pair actually talks.

- [ ] **Step 1: Write the failing client test**

`console/src/api/__tests__/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadClientWith(base: string | undefined) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE', base ?? '')
  return await import('../client')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('api client base URL', () => {
  it('uses relative paths in development, so the Vite proxy handles them', async () => {
    const fetchSpy = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }))
    vi.stubGlobal('fetch', fetchSpy)

    const client = await loadClientWith('')
    await client.fetchLatestFindings()

    expect(fetchSpy).toHaveBeenCalledWith('/api/runs/latest/findings', undefined)
  })

  it('prefixes the configured base in production, because there is no proxy there', async () => {
    const fetchSpy = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }))
    vi.stubGlobal('fetch', fetchSpy)

    const client = await loadClientWith('https://signal-desk-service.onrender.com')
    await client.fetchLatestFindings()

    expect(fetchSpy).toHaveBeenCalledWith(
      'https://signal-desk-service.onrender.com/api/runs/latest/findings',
      undefined,
    )
  })

  it('tolerates a trailing slash on the configured base', async () => {
    // Pasting a URL out of a dashboard is how this happens, and a doubled slash
    // is a 404 that looks like a routing bug.
    const fetchSpy = vi.fn(async () => ({ ok: true, status: 200, json: async () => [] }))
    vi.stubGlobal('fetch', fetchSpy)

    const client = await loadClientWith('https://signal-desk-service.onrender.com/')
    await client.fetchLatestFindings()

    expect(fetchSpy).toHaveBeenCalledWith(
      'https://signal-desk-service.onrender.com/api/runs/latest/findings',
      undefined,
    )
  })

  it('throws with the status and path when the service answers badly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })))

    const client = await loadClientWith('')

    await expect(client.fetchLatestFindings()).rejects.toThrow(/503/)
    await expect(client.fetchLatestFindings()).rejects.toThrow(/runs\/latest\/findings/)
  })

  it('posts JSON with a content-type when asking a question', async () => {
    const fetchSpy = vi.fn(async () => ({
      ok: true, status: 200, json: async () => ({ answer: 'x', trace: [] }),
    }))
    vi.stubGlobal('fetch', fetchSpy)

    const client = await loadClientWith('')
    await client.askQuestion('run-1', 'Why is V07 flagged?')

    const [, init] = fetchSpy.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ runId: 'run-1', question: 'Why is V07 flagged?' })
  })
})
```

Two of these earn their place beyond coverage. The 503 test: a spun-down Render
instance is the single most likely production failure, and an error naming neither
the status nor the path is undiagnosable from a phone at a venue. The
trailing-slash test: it **fails** against Task 17's `client.ts` as written, and
that is a real defect, not a hypothetical.

- [ ] **Step 2: Run it and confirm which tests fail**

Run: `cd console && npm test -- client`
Expected: the trailing-slash test FAILS with a doubled slash in the asserted path.
The other four should PASS against Task 17's `client.ts`.

Four tests passing on first run is the correct outcome — they pin behaviour that
already exists deliberately. Do not delete a test because it passed.

- [ ] **Step 3: Fix the trailing-slash defect**

In `console/src/api/client.ts`:

```ts
const base = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')
```

Run: `cd console && npm test -- client`
Expected: PASS, 5 tests.

- [ ] **Step 4: Commit the lockfile if it is not already tracked**

Render's build runs `npm ci`, which **fails outright without a lockfile** — and
that is the correct behaviour, since `npm install` on a build server can silently
resolve different versions than the ones tested.

```bash
git ls-files console/package-lock.json
```

Expected: the path is printed. If it is empty, `git add console/package-lock.json`
and include it in this task's commit.

- [ ] **Step 5: Document the build-time variable**

`console/.env.production.example` (committed, placeholder only):

```
# The Render service URL from Task 16. Set the real value as an envVar on the
# Render static site, not here — this file documents the variable's name.
VITE_API_BASE=https://REPLACE-ME.onrender.com
```

**Do not commit a `.env.production`.** `VITE_API_BASE` is not a secret, but Vite
inlines every `VITE_`-prefixed variable into the built bundle, so keeping real
values out of the repo matters more here, not less: the next variable someone adds
might be one that does matter.

- [ ] **Step 6: Show the operator which API the console is talking to**

A console silently pointing at the wrong service is a confusing five minutes on
stage. Add one line to `App.tsx`'s header:

```tsx
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#52525b' }}>
          {import.meta.env.VITE_API_BASE || 'local (dev proxy)'}
        </span>
```

- [ ] **Step 7: Add the static site to the blueprint**

Append to `render.yaml`, under the existing `services:` list from Task 16:

```yaml
  - type: web
    name: signal-desk-console
    runtime: static
    rootDir: console
    plan: free
    buildCommand: npm ci && npm run build
    staticPublishPath: ./dist
    autoDeploy: false
    envVars:
      # Vite 7 requires Node 20.19+ or 22.12+. Render's default is older, and
      # rootDir: console means the repo-root .nvmrc is not what it reads — so the
      # version is pinned explicitly here.
      - key: NODE_VERSION
        value: 22.12.0
      # Inlined into the bundle at BUILD time, not read at runtime. Set it to the
      # service URL from Task 16.
      - key: VITE_API_BASE
        sync: false
    routes:
      # Without this, a refresh on any client-side route returns Render's 404
      # instead of the app.
      - type: rewrite
        source: /*
        destination: /index.html
```

Note what `rootDir: console` changes: the build runs inside `console/`, so
`staticPublishPath` is relative to it, and the repo-root `.npmrc`
(`engine-strict=true`) is **not** read. `NODE_VERSION` is doing the job
`engine-strict` does locally.

- [ ] **Step 8: Build for production locally, before involving Render**

```bash
cd console
nvm use
VITE_API_BASE=https://<your-service>.onrender.com npm run build
npx vite preview --port 4173 &
sleep 3
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:4173/
```

Expected: `tsc -b` clean, a `dist/` directory, HTTP 200. Then open
`http://localhost:4173` in a browser.

**It will fail to load findings, and that is the expected result here** — the
service has not been told to allow this origin yet. Confirm the browser console
shows a **CORS** error, not a 404 and not a DNS failure. A CORS error proves the
base URL is right and only the allowlist is missing; the other two mean Step 7 or
Task 16 is wrong.

- [ ] **Step 9: Deploy it**

Render picks up the new service from the blueprint (dashboard → the blueprint →
sync / apply). Set `VITE_API_BASE` on the console service to the Task 16 service
URL, then deploy.

Expected: a `https://signal-desk-console.onrender.com` URL. **Record it.**

- [ ] **Step 10: Close the CORS loop on the service**

Set `SIGNALDESK_CORS_ORIGINS` on the **service** to the console URL plus
localhost, and redeploy it:

```
https://signal-desk-console.onrender.com,http://localhost:5173
```

Spring's relaxed binding maps that variable onto `signaldesk.cors.origins`.
Verify from the command line before opening a browser:

```bash
curl -s -i -X OPTIONS "https://<your-service>.onrender.com/api/runs/latest/findings" \
  -H "Origin: https://signal-desk-console.onrender.com" \
  -H "Access-Control-Request-Method: GET" | grep -i 'access-control-allow-origin'
```

Expected: the header echoes the console origin. If it is absent, the environment
variable did not take — check for a stray `@CrossOrigin` (Task 16 Step 4) before
suspecting Render.

- [ ] **Step 11: Prove the deployed pair end to end**

Open the console URL in a browser and, **with the laptop service stopped** so
there is no chance of reading a local API:

- [ ] The findings list renders, ranked, already populated
- [ ] The header shows the Render service URL, not "local (dev proxy)"
- [ ] Expanding a row shows references, the rule that fired, and `evidenceSql`
- [ ] The feed-health strip shows a non-zero quarantined count
- [ ] "Sweep now" returns a new runId and the list refreshes
- [ ] The brief preview renders, and **do not press send** — one real Slack
      message per intentional demo, not one per smoke test

If the first load times out, that is the free tier's cold start on the service
(30–90s). Reload after 60 seconds before investigating anything.

- [ ] **Step 12: Record both URLs where they will be found**

Add to `README.md`, under a new "Deployed" heading: both Render URLs, `GET
/api/health` as the liveness check, one sentence on why **both** are on Render
rather than the spec's Vercel split, and one sentence stating that the scored demo
runs on the laptop and why (cold start, venue network). Task 24's deck reuses this
wording — and must not say Vercel.

- [ ] **Step 13: Run both suites**

Run: `cd console && npm test` — expected PASS, 21 tests.
Run: `./scripts/mvn.sh -q test` — expected PASS.

- [ ] **Step 14: Break-it-to-prove-it**

Delete the `routes` block from `render.yaml`, redeploy, and load a deep link.
Expected: Render's 404 instead of the app. Restore.

Then revert the Step 3 trailing-slash fix and rerun the client tests. Expected:
the trailing-slash test FAILS. Restore.

- [ ] **Step 15: Commit**

```bash
git add render.yaml console README.md
git commit -m "feat(deploy): console as a Render static site, API base configurable, deployed pair verified"
```

---

### Task 20: Metrics 4 and 5 (~0 h 45)

**Files:**
- Modify: `service/src/main/resources/application.yaml` (activate the metrics)
- Test: `service/src/test/java/com/signaldesk/registry/DuckDbMetricRepositoryTest.java`
- Test: `service/src/test/java/com/signaldesk/agent/SweepTest.java` (re-pin the distribution)

**Interfaces:** no new types. `cost_per_trip` and `night_compliance` were defined
in Task 5; this task turns them on and proves them.

**No code is needed to add a metric** — which was the point of Task 5's shape. If
this task requires new Java, something in the registry was wrong.

- [ ] **Step 1: Activate them**

```yaml
  metrics:
    active: ota,sla_breach,vendor_ota,cost_per_trip,night_compliance
```

- [ ] **Step 2: Add their SQL tests**

Remove `cost_per_trip` and `night_compliance` from any skip list, then add:

```java
    @Test
    void costPerTripIsAPlausibleRupeeFigure() {
        double cost = repo.evaluate(registry.byId("cost_per_trip"), Slice.all(), window).orElseThrow();
        System.out.printf("MEASURED cost_per_trip=%.2f INR%n", cost);
        assertThat(cost).as("integer rupees, one trip").isBetween(100.0, 2000.0);
    }

    @Test
    void theDegradingVendorAlsoCostsMore() {
        Metric cost = registry.byId("cost_per_trip");
        double bad = repo.evaluate(cost, new Slice(Dimension.VENDOR, FixtureGenerator.DEGRADING_VENDOR),
                window).orElseThrow();
        double peer = repo.evaluate(cost, new Slice(Dimension.VENDOR, "V03"), window).orElseThrow();
        System.out.printf("MEASURED cost V07=%.2f V03=%.2f%n", bad, peer);
        assertThat(bad).as("two metrics corroborating one vendor is what makes the brief a decision")
                .isGreaterThan(peer);
    }

    @Test
    void nightComplianceCountsOnlyNightLogoutTrips() {
        double all = repo.evaluate(registry.byId("night_compliance"), Slice.all(), window)
                .orElseThrow();
        System.out.printf("MEASURED night_compliance=%.2f%%%n", all);
        assertThat(all).isBetween(0.0, 100.0);
        assertThat(all).as("the fixture plants escort failures, so it cannot be a clean 100")
                .isLessThan(100.0);
    }

    @Test
    void nightComplianceDegradesRatherThanLyingWhenTheColumnIsAbsent() throws Exception {
        // union_by_name means a dataset without night_escort loads fine; coverage
        // must then be 0 so the rule caps at WATCH.
        //
        // trips is a TABLE (ingest materialises it), so this drops the column
        // directly. A view named trips over a table named trips would be circular
        // and DuckDB rejects it.
        try (java.sql.Statement s = conn.createStatement()) {
            s.execute("ALTER TABLE trips DROP COLUMN night_escort");
        }
        double coverage = repo.coverage(registry.byId("night_compliance"), Slice.all(), window);

        assertThat(coverage).as("a metric whose own required column is gone reports 0.0")
                .isEqualTo(0.0);
    }
```

- [ ] **Step 3: Run and read the measurements**

Run: `./scripts/mvn.sh -q test -Dtest=DuckDbMetricRepositoryTest`
Expected: PASS. Record the MEASURED lines.

- [ ] **Step 4: Re-run the sweep and re-pin the distribution**

Run: `./scripts/mvn.sh -q test -Dtest=SweepTest`

Two metrics more means more findings, so the pinned counts from Task 10 will
fail. **Re-measure and re-pin — do not widen the bands to swallow both cases.**
Update the `MEASURED` comment in both `DeltaRule` and `SweepTest`.

Check specifically that `night_compliance` produces a `BREACH` somewhere: its
target is a hard 100, so any escort failure at all should breach. If it does not,
the `hardTarget` path is not wired and deviation 2 was implemented wrongly.

- [ ] **Step 5: Commit**

```bash
git add service
git commit -m "feat(registry): activate cost_per_trip and night_compliance, re-pin the distribution"
```

---

### Task 21: Vernacular feedback and metric 6 (~1 h 00)

**Files:**
- Create: `service/src/main/java/com/signaldesk/ingest/SentimentLexicon.java`, `FeedbackNormaliser.java`
- Create: `service/src/main/java/com/signaldesk/model/Translator.java`
- Test: `service/src/test/java/com/signaldesk/ingest/SentimentLexiconTest.java`, `FeedbackNormaliserTest.java`
- Modify: `application.yaml` (activate `experience`)

**Interfaces:**
- Consumes: `ModelClient`, DuckDB `Connection`, the `feedback` view.
- Produces:
  - `SentimentLexicon.score(String englishComment)` → `-1 | 0 | +1`
  - `Translator.toEnglish(String comment, String language)` → `Optional<String>`
  - `FeedbackNormaliser.normalise()` — materialises
    `feedback_normalised(trip_id, employee_id, rating, comment, comment_en, language, sentiment)`
  - `FeedbackNormaliser.untranslatedCount()`

**This is the one thing a general-purpose competitor cannot easily copy** — and it
must degrade, never fail. Untranslated comments contribute sentiment 0 and count
as `nullCriticalFields`, so confidence falls and the rule caps at `WATCH`. The
table is materialised once at startup and cached, so the sweep stays
deterministic even though translation is not.

- [ ] **Step 1: Write the failing lexicon tests**

`service/src/test/java/com/signaldesk/ingest/SentimentLexiconTest.java`:

```java
package com.signaldesk.ingest;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class SentimentLexiconTest {

    @ParameterizedTest
    @CsvSource({
        "'Driver was punctual and polite', 1",
        "'Cab arrived on time, driver was good', 1",
        "'Waited forty minutes with no update', -1",
        "'The cab was very late and nobody informed me', -1",
        "'Trip completed', 0",
        "'', 0",
    })
    void scoresPolarityFromTheTranslatedText(String comment, int expected) {
        assertThat(SentimentLexicon.score(comment)).isEqualTo(expected);
    }

    @Test
    void isDeterministicAndCaseInsensitive() {
        assertThat(SentimentLexicon.score("DRIVER WAS PUNCTUAL"))
                .isEqualTo(SentimentLexicon.score("driver was punctual"));
    }

    @Test
    void aMixedCommentResolvesToTheStrongerSideRatherThanCancellingToZero() {
        // "late" outweighs "polite": two negative markers against one positive.
        assertThat(SentimentLexicon.score("Driver was polite but very late and no update"))
                .isEqualTo(-1);
    }

    @Test
    void returnsNeutralForNullSoAnUntranslatedCommentNeverThrows() {
        assertThat(SentimentLexicon.score(null)).isEqualTo(0);
    }
}
```

- [ ] **Step 2: Write the lexicon**

`SentimentLexicon.java`:

```java
package com.signaldesk.ingest;

import java.util.List;

/**
 * Deterministic, in Java, over the TRANSLATED comment. The model does language;
 * this arithmetic does not pass through it — which is what keeps section 1.1
 * intact while still letting metric 6 read what an employee actually wrote.
 */
public final class SentimentLexicon {

    private static final List<String> NEGATIVE = List.of(
            "late", "delay", "delayed", "waited", "waiting", "no update", "nobody informed",
            "not informed", "rude", "dirty", "unsafe", "cancelled", "no show", "breakdown");

    private static final List<String> POSITIVE = List.of(
            "punctual", "on time", "polite", "good", "clean", "comfortable", "safe",
            "helpful", "courteous", "smooth");

    private SentimentLexicon() {}

    public static int score(String englishComment) {
        if (englishComment == null || englishComment.isBlank()) {
            return 0;
        }
        String s = englishComment.toLowerCase();
        long neg = NEGATIVE.stream().filter(s::contains).count();
        long pos = POSITIVE.stream().filter(s::contains).count();
        if (neg > pos) {
            return -1;
        }
        return pos > neg ? 1 : 0;
    }
}
```

Run: `./scripts/mvn.sh -q test -Dtest=SentimentLexiconTest`
Expected: PASS, 9 cases.

- [ ] **Step 3: Write the failing normaliser tests**

`service/src/test/java/com/signaldesk/ingest/FeedbackNormaliserTest.java`:

```java
package com.signaldesk.ingest;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.model.Translator;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.Optional;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class FeedbackNormaliserTest {

    private Connection conn;

    @BeforeEach
    void open() throws Exception {
        conn = DriverManager.getConnection("jdbc:duckdb:");
    }

    @AfterEach
    void close() throws Exception {
        conn.close();
    }

    private void loadFeedback(Path dir) throws Exception {
        Files.writeString(dir.resolve("feedback.csv"), """
                trip_id,employee_id,rating,comment,language
                T1,E1,5,"Driver was punctual and polite",en
                T2,E2,2,"Cab bahut late tha, koi soochna nahi mili",hi
                T3,E3,4,"Trip completed",en
                """);
        new DuckDbLoader(conn, feed -> dir.resolve(feed.fileName()).toString()).load(Feed.FEEDBACK);
    }

    @Test
    void retainsTheOriginalCommentVerbatimAlongsideTheTranslation(@TempDir Path dir) throws Exception {
        loadFeedback(dir);
        Translator translator = (comment, language) ->
                "hi".equals(language) ? Optional.of("The cab was very late and no update was given")
                                      : Optional.of(comment);

        new FeedbackNormaliser(conn, translator).normalise();

        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery(
                     "SELECT comment, comment_en, sentiment FROM feedback_normalised WHERE trip_id='T2'")) {
            rs.next();
            assertThat(rs.getString("comment")).isEqualTo("Cab bahut late tha, koi soochna nahi mili");
            assertThat(rs.getString("comment_en")).contains("very late");
            assertThat(rs.getInt("sentiment")).isEqualTo(-1);
        }
    }

    @Test
    void aTranslationFailureDegradesRatherThanBlockingTheSweep(@TempDir Path dir) throws Exception {
        loadFeedback(dir);
        Translator failing = (comment, language) ->
                "hi".equals(language) ? Optional.empty() : Optional.of(comment);

        FeedbackNormaliser n = new FeedbackNormaliser(conn, failing);
        n.normalise();

        assertThat(n.untranslatedCount()).isEqualTo(1);
        try (Statement s = conn.createStatement();
             ResultSet rs = s.executeQuery(
                     "SELECT count(*) FROM feedback_normalised WHERE sentiment = 0")) {
            rs.next();
            assertThat(rs.getLong(1)).as("untranslated rows are neutral, not dropped")
                    .isGreaterThanOrEqualTo(2);
        }
    }

    @Test
    void aTranslatorThatThrowsIsTreatedAsAFailureNotAnOutage(@TempDir Path dir) throws Exception {
        loadFeedback(dir);
        Translator exploding = (comment, language) -> {
            throw new RuntimeException("Sarvam unreachable");
        };

        FeedbackNormaliser n = new FeedbackNormaliser(conn, exploding);
        n.normalise();

        assertThat(n.untranslatedCount()).isEqualTo(3);
    }

    @Test
    void englishCommentsAreNotSentToTheModelAtAll(@TempDir Path dir) throws Exception {
        loadFeedback(dir);
        java.util.List<String> calls = new java.util.ArrayList<>();
        Translator counting = (comment, language) -> {
            calls.add(language);
            return Optional.of(comment);
        };

        new FeedbackNormaliser(conn, counting).normalise();

        assertThat(calls).as("translating English to English burns credits for nothing")
                .containsOnly("hi");
    }
}
```

- [ ] **Step 4: Write the translator and the normaliser**

`Translator.java`:

```java
package com.signaldesk.model;

import java.util.Optional;

/** Language only. A failure degrades a metric's confidence; it never blocks a sweep. */
public interface Translator {
    Optional<String> toEnglish(String comment, String language);
}
```

`SarvamTranslator` (in the same package), using `ModelClient`:

```java
package com.signaldesk.model;

import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Component;

@Component
public class SarvamTranslator implements Translator {

    private final ModelClient model;

    public SarvamTranslator(ModelClient model) {
        this.model = model;
    }

    @Override
    public Optional<String> toEnglish(String comment, String language) {
        if (comment == null || comment.isBlank() || "en".equalsIgnoreCase(language)) {
            return Optional.ofNullable(comment);
        }
        try {
            String out = model.complete(List.of(
                    new ChatMessage("system",
                            "Translate the employee's transport feedback into English. "
                                    + "Reply with the translation only, no commentary."),
                    new ChatMessage("user", comment)));
            return out.isBlank() ? Optional.empty() : Optional.of(out.trim());
        } catch (RuntimeException e) {
            return Optional.empty();
        }
    }
}
```

`FeedbackNormaliser.java`:

```java
package com.signaldesk.ingest;

import com.signaldesk.model.Translator;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

/**
 * Materialised once, then cached: translation is not deterministic, and the
 * sweep must be. The original comment is retained verbatim so the narrative can
 * quote it alongside the translation.
 */
@Component
public class FeedbackNormaliser {

    private final Connection conn;
    private final Translator translator;
    private final AtomicLong untranslated = new AtomicLong();

    public FeedbackNormaliser(Connection conn, Translator translator) {
        this.conn = conn;
        this.translator = translator;
    }

    public void normalise() {
        try (Statement s = conn.createStatement()) {
            s.execute("""
                    CREATE OR REPLACE TABLE feedback_normalised (
                      trip_id VARCHAR, employee_id VARCHAR, rating INTEGER,
                      comment VARCHAR, comment_en VARCHAR, language VARCHAR, sentiment INTEGER
                    )
                    """);
        } catch (SQLException e) {
            throw new DuckDbLoader.IngestException("could not create feedback_normalised", e);
        }

        String insert = "INSERT INTO feedback_normalised VALUES (?,?,?,?,?,?,?)";
        try (Statement read = conn.createStatement();
             ResultSet rs = read.executeQuery(
                     "SELECT trip_id, employee_id, rating, comment, language FROM feedback");
             PreparedStatement write = conn.prepareStatement(insert)) {
            while (rs.next()) {
                String comment = rs.getString("comment");
                String language = rs.getString("language");
                Optional<String> english = translate(comment, language);
                if (english.isEmpty()) {
                    untranslated.incrementAndGet();
                }
                write.setString(1, rs.getString("trip_id"));
                write.setString(2, rs.getString("employee_id"));
                write.setInt(3, rs.getInt("rating"));
                write.setString(4, comment);
                write.setString(5, english.orElse(null));
                write.setString(6, language);
                write.setInt(7, SentimentLexicon.score(english.orElse(null)));
                write.addBatch();
            }
            write.executeBatch();
        } catch (SQLException e) {
            throw new DuckDbLoader.IngestException("could not normalise feedback", e);
        }
    }

    private Optional<String> translate(String comment, String language) {
        try {
            return translator.toEnglish(comment, language);
        } catch (RuntimeException e) {
            return Optional.empty();
        }
    }

    public long untranslatedCount() {
        return untranslated.get();
    }
}
```

- [ ] **Step 5: Run the tests, then activate metric 6**

Run: `./scripts/mvn.sh -q test -Dtest=FeedbackNormaliserTest`
Expected: PASS, 4 tests.

Then wire it so the `feedback` view is guaranteed to exist first. **Do not call
`normalise()` from inside `DuckDbConfig`'s loader `@Bean` method** — a bean
factory method that also triggers unrelated work is the wrong seam, and the
ordering would be a comment rather than a fact. Instead make the dependency
explicit and let the container enforce it:

```java
@Component
public class FeedbackNormaliser {

    private final Connection conn;
    private final Translator translator;
    private final AtomicLong untranslated = new AtomicLong();

    /** DuckDbLoader is injected for ordering, not use: the feedback view must
     *  exist before this bean is constructed. */
    public FeedbackNormaliser(Connection conn, Translator translator, DuckDbLoader loader) {
        this.conn = conn;
        this.translator = translator;
    }

    @jakarta.annotation.PostConstruct
    void normaliseOnStartup() {
        normalise();
    }

    // … normalise() and untranslatedCount() unchanged
}
```

`SweepScheduler`'s `ApplicationReadyEvent` sweep runs after every bean is
constructed, so `feedback_normalised` is populated before the first sweep reads
it. Update `FeedbackNormaliserTest` to pass `null` for the loader — the tests
load the feedback view themselves, so the ordering dependency is not exercised
there.

Then activate the metric:

```yaml
  metrics:
    active: ota,sla_breach,vendor_ota,cost_per_trip,night_compliance,experience
```

Remove the `experience` skip from `DuckDbMetricRepositoryTest`, and add:

```java
    @Test
    void experienceIsAScoreBetweenOneAndFive() {
        double score = repo.evaluate(registry.byId("experience"), Slice.all(), window).orElseThrow();
        System.out.printf("MEASURED experience=%.2f%n", score);
        assertThat(score).isBetween(1.0, 5.0);
    }
```

This test needs `feedback_normalised` to exist, so add a normalise call to the
test's `@BeforeEach` using a pass-through stub translator — the metric's SQL is
what is under test here, not translation.

- [ ] **Step 6: Re-pin the distribution one last time and confirm degradation**

Run: `./scripts/mvn.sh -q test`. Re-measure and re-pin `SweepTest`'s
distribution, as in Task 20 Step 4.

Then run the whole suite with `SARVAM_API_KEY` unset. Expected: PASS. Every
non-English comment is untranslated, `experience` reports low confidence, and its
rule caps at `WATCH` — **the metric degrades rather than failing the sweep**,
which is exactly the behaviour spec §5.2 demands. Confirm the console shows
`experience` at `WATCH` with a visible confidence figure, not an error.

- [ ] **Step 7: Commit**

```bash
git add service
git commit -m "feat(ingest): vernacular feedback normalisation feeding the experience metric"
```

---

### Task 22: The four model tools and the interrogation endpoint (~1 h 15)

**Files:**
- Create: `service/src/main/java/com/signaldesk/model/tools/Tool.java`, `ToolRegistry.java`, `ToolCallTrace.java`, `ListMetricsTool.java`, `GetMetricTool.java`, `ListFindingsTool.java`, `ExplainFindingTool.java`
- Create: `service/src/main/java/com/signaldesk/model/Interrogator.java`
- Create: `service/src/main/java/com/signaldesk/api/AskController.java`
- Test: `service/src/test/java/com/signaldesk/model/tools/ToolRegistryTest.java`
- Test: `service/src/test/java/com/signaldesk/model/InterrogatorTest.java`

**Interfaces:**
- Consumes: `MetricRegistry`, `MetricRepository`, `ReferenceResolver`, `FindingStore`, `ModelClient`.
- Produces:
  - `interface Tool { String name(); String description(); Map<String,String> parameters(); String invoke(Map<String,String> args); }`
  - `ToolRegistry.byName(String)`, `ToolRegistry.all()`
  - `record ToolCallTrace(String tool, Map<String,String> args, String result)`
  - `Interrogator.ask(String runId, String question)` → `record Answer(String answer, List<ToolCallTrace> trace)`
  - `POST /api/ask` → `{ answer, trace[] }`

**There is no `run_sql` tool.** That is the deliberate difference between this and
a text-to-SQL demo, and `InvariantTest.noToolExposesRawSqlExecution` from Task 5
already enforces it. Arguments are validated against the §5.3 enumerations
*before* execution; an unknown dimension or metric id is rejected with a message
naming the valid values.

- [ ] **Step 1: Write the failing validation tests**

`service/src/test/java/com/signaldesk/model/tools/ToolRegistryTest.java`:

```java
package com.signaldesk.model.tools;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;

class ToolRegistryTest {

    // Wire a registry against the same stubs used in ReferenceResolverTest; see
    // that file's StubRepository. The four tools under test are pure functions of
    // registry + repository + store.

    @Test
    void exposesExactlyFourToolsAndNoneOfThemRunsSql() {
        ToolRegistry tools = TestTools.registry();

        assertThat(tools.all()).extracting(Tool::name)
                .containsExactlyInAnyOrder("list_metrics", "get_metric",
                        "list_findings", "explain_finding");
        assertThat(tools.all()).extracting(Tool::name).doesNotContain("run_sql");
    }

    @Test
    void anUnknownDimensionIsRefusedWithTheValidValuesNamed() {
        String result = TestTools.registry().byName("get_metric")
                .invoke(Map.of("metricId", "ota", "dimension", "route", "value", "R1"));

        assertThat(result).containsIgnoringCase("unknown dimension");
        assertThat(result).contains("route");
        assertThat(result).contains("VENDOR").contains("SITE").contains("SHIFT");
    }

    @Test
    void anUnknownMetricIdIsRefusedWithTheValidIdsNamed() {
        String result = TestTools.registry().byName("get_metric")
                .invoke(Map.of("metricId", "on_time", "dimension", "NONE"));

        assertThat(result).containsIgnoringCase("unknown metric");
        assertThat(result).contains("ota");
    }

    @Test
    void aMissingRequiredArgumentIsRefusedRatherThanDefaulted() {
        String result = TestTools.registry().byName("explain_finding").invoke(Map.of());

        assertThat(result).containsIgnoringCase("findingId");
    }

    @Test
    void anUnknownToolNameIsRefused() {
        assertThat(TestTools.registry().byName("drop_tables")).isNull();
    }

    @Test
    void explainFindingReturnsTheEvidenceSqlAndTheRuleThatFired() {
        String result = TestTools.registry().byName("explain_finding")
                .invoke(Map.of("findingId", TestTools.KNOWN_FINDING_ID));

        assertThat(result).contains("evidenceSql").contains("cause");
    }
}
```

Write `TestTools` as a small test fixture that builds a `ToolRegistry` over the
stub repository and a `FindingStore` pre-loaded with one known finding, exposing
`KNOWN_FINDING_ID`.

- [ ] **Step 2: Write the tool interface and registry**

`Tool.java`:

```java
package com.signaldesk.model.tools;

import java.util.Map;

/**
 * The model's ONLY access to data. It cannot reach the database except through
 * these four, and every argument is validated against the enumerations in spec
 * section 5.3 before execution — never guessed at, never passed to SQL.
 */
public interface Tool {

    String name();

    String description();

    /** Parameter name to a human description, for the tool schema. */
    Map<String, String> parameters();

    /** Returns a compact text result, or a refusal naming the valid values. */
    String invoke(Map<String, String> args);
}
```

`ToolRegistry.java`:

```java
package com.signaldesk.model.tools;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

@Component
public class ToolRegistry {

    private final Map<String, Tool> byName;

    public ToolRegistry(List<Tool> tools) {
        this.byName = tools.stream().collect(Collectors.toMap(Tool::name, Function.identity()));
    }

    public List<Tool> all() {
        return List.copyOf(byName.values());
    }

    /** Null for an unknown name: the model is told, not obeyed. */
    public Tool byName(String name) {
        return byName.get(name);
    }
}
```

`ToolCallTrace.java`:

```java
package com.signaldesk.model.tools;

import java.util.Map;

/** Shown in the console so the reasoning is visible rather than asserted. */
public record ToolCallTrace(String tool, Map<String, String> args, String result) {}
```

- [ ] **Step 3: Write the four tools**

Each is a `@Component`. `ListMetricsTool` returns id, label, unit and declared
references for every metric. `GetMetricTool` validates `metricId` through
`MetricRegistry.byId` and `dimension` through `Dimension.parse` — **both of which
already throw with the valid values named**, so the tool's job is to catch and
return that message rather than to re-implement validation:

```java
package com.signaldesk.model.tools;

import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.Metric;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.registry.MetricRepository;
import com.signaldesk.registry.ReferenceResolver;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import java.time.Clock;
import java.util.Map;
import java.util.OptionalDouble;
import org.springframework.stereotype.Component;

@Component
public class GetMetricTool implements Tool {

    private final MetricRegistry registry;
    private final MetricRepository repo;
    private final ReferenceResolver resolver;
    private final Clock clock;

    public GetMetricTool(MetricRegistry registry, MetricRepository repo,
                         ReferenceResolver resolver, Clock clock) {
        this.registry = registry;
        this.repo = repo;
        this.resolver = resolver;
        this.clock = clock;
    }

    @Override public String name() { return "get_metric"; }

    @Override public String description() {
        return "Read one metric for one slice over the current window, with its reference points.";
    }

    @Override public Map<String, String> parameters() {
        return Map.of(
                "metricId", "one of " + registry.ids(),
                "dimension", "one of VENDOR, SITE, SHIFT, MODE, DIRECTION, NONE",
                "value", "the dimension value; omit when dimension is NONE");
    }

    @Override public String invoke(Map<String, String> args) {
        String metricId = args.get("metricId");
        if (metricId == null) {
            return "missing required argument metricId; valid ids are " + registry.ids();
        }
        Metric metric;
        Slice slice;
        try {
            metric = registry.byId(metricId);
            Dimension dim = Dimension.parse(args.getOrDefault("dimension", "NONE"));
            slice = dim == Dimension.NONE ? Slice.all() : new Slice(dim, args.get("value"));
        } catch (IllegalArgumentException e) {
            return e.getMessage();   // already names the valid values
        }

        Window window = Window.weekEnding(clock.millis());
        OptionalDouble observed = repo.evaluate(metric, slice, window);
        if (observed.isEmpty()) {
            return metric.id() + " has no data for " + slice.label() + " in " + window.label();
        }
        StringBuilder sb = new StringBuilder()
                .append(metric.id()).append(" ").append(slice.label())
                .append(" observed=").append(String.format("%.2f", observed.getAsDouble()))
                .append(metric.unit());
        resolver.resolve(metric, slice, window).forEach(r -> sb.append(" | ")
                .append(r.label()).append("=").append(String.format("%.2f", r.value())));
        return sb.toString();
    }
}
```

`ListMetricsTool.java`:

```java
package com.signaldesk.model.tools;

import com.signaldesk.registry.Metric;
import com.signaldesk.registry.MetricRegistry;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class ListMetricsTool implements Tool {

    private final MetricRegistry registry;

    public ListMetricsTool(MetricRegistry registry) {
        this.registry = registry;
    }

    @Override public String name() { return "list_metrics"; }

    @Override public String description() {
        return "List every metric with its label, unit, and the reference points it is judged against.";
    }

    @Override public Map<String, String> parameters() {
        return Map.of();
    }

    @Override public String invoke(Map<String, String> args) {
        StringBuilder sb = new StringBuilder();
        for (Metric m : registry.active()) {
            sb.append(m.id()).append(" — ").append(m.label())
              .append(" (").append(m.unit()).append(", ")
              .append(m.better()).append(" is better)")
              .append(" judged against ").append(m.refs());
            if (m.target() != null) {
                sb.append(", target ").append(String.format("%.2f", m.target()));
            }
            sb.append('\n');
        }
        return sb.toString();
    }
}
```

`ListFindingsTool.java`:

```java
package com.signaldesk.model.tools;

import com.signaldesk.agent.FindingStore;
import com.signaldesk.agent.SweepRun;
import com.signaldesk.registry.MetricRegistry;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Tier;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Component;

@Component
public class ListFindingsTool implements Tool {

    private final FindingStore store;
    private final MetricRegistry registry;

    public ListFindingsTool(FindingStore store, MetricRegistry registry) {
        this.store = store;
        this.registry = registry;
    }

    @Override public String name() { return "list_findings"; }

    @Override public String description() {
        return "List the ranked findings for a run, optionally filtered by tier or metric.";
    }

    @Override public Map<String, String> parameters() {
        return Map.of(
                "runId", "the run id, or the literal 'latest'",
                "tier", "optional; one of " + Arrays.toString(Tier.values()),
                "metricId", "optional; one of " + registry.ids());
    }

    @Override public String invoke(Map<String, String> args) {
        String runId = args.getOrDefault("runId", "latest");
        Optional<SweepRun> run = "latest".equals(runId) ? store.latest() : store.get(runId);
        if (run.isEmpty()) {
            return "unknown runId '" + runId + "'; use 'latest' or one of " + store.runIds();
        }

        Tier tierFilter = null;
        if (args.get("tier") != null && !args.get("tier").isBlank()) {
            try {
                tierFilter = Tier.valueOf(args.get("tier").toUpperCase());
            } catch (IllegalArgumentException e) {
                return "unknown tier '" + args.get("tier") + "'; valid values are "
                        + Arrays.toString(Tier.values());
            }
        }
        String metricFilter = args.get("metricId");
        if (metricFilter != null && !metricFilter.isBlank()) {
            try {
                registry.byId(metricFilter);
            } catch (IllegalArgumentException e) {
                return e.getMessage();   // already names the valid ids
            }
        }

        final Tier tier = tierFilter;
        List<Finding> matching = run.get().findings().stream()
                .filter(f -> tier == null || f.tier() == tier)
                .filter(f -> metricFilter == null || metricFilter.isBlank()
                        || f.metricId().equals(metricFilter))
                .limit(25)                       // the model sees aggregates, not a wall
                .toList();
        if (matching.isEmpty()) {
            return "no findings match that filter in run " + run.get().runId();
        }

        StringBuilder sb = new StringBuilder("run ").append(run.get().runId())
                .append(", worst first:\n");
        for (Finding f : matching) {
            sb.append(f.id()).append(' ').append(f.metricId())
              .append(" [").append(f.slice().label()).append("] ")
              .append(f.tier()).append(" observed=")
              .append(String.format("%.2f", f.observed()))
              .append(" cause=").append(f.cause())
              .append(" confidence=").append(String.format("%.2f", f.confidence()))
              .append('\n');
        }
        return sb.toString();
    }
}
```

`ExplainFindingTool.java`:

```java
package com.signaldesk.model.tools;

import com.signaldesk.agent.FindingStore;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class ExplainFindingTool implements Tool {

    private final FindingStore store;

    public ExplainFindingTool(FindingStore store) {
        this.store = store;
    }

    @Override public String name() { return "explain_finding"; }

    @Override public String description() {
        return "Explain one finding: its references, the rule that fired, and the exact "
                + "query that produced the number.";
    }

    @Override public Map<String, String> parameters() {
        return Map.of("findingId", "the finding id from list_findings");
    }

    @Override public String invoke(Map<String, String> args) {
        String id = args.get("findingId");
        if (id == null || id.isBlank()) {
            return "missing required argument findingId; get one from list_findings";
        }
        return store.finding(id)
                .map(ExplainFindingTool::render)
                .orElse("unknown findingId '" + id + "'; get one from list_findings");
    }

    private static String render(Finding f) {
        StringBuilder sb = new StringBuilder()
                .append("finding ").append(f.id()).append('\n')
                .append("metric=").append(f.metricId())
                .append(" slice=").append(f.slice().label())
                .append(" window=").append(f.window().label()).append('\n')
                .append("observed=").append(String.format("%.2f", f.observed())).append('\n');
        for (Reference r : f.refs()) {
            sb.append("reference ").append(r.kind()).append(' ').append(r.label())
              .append('=').append(String.format("%.2f", r.value())).append('\n');
        }
        sb.append("tier=").append(f.tier())
          .append(" cause=").append(f.cause())
          .append(" gap=").append(String.format("%.2f", f.gap()))
          .append(" confidence=").append(String.format("%.2f", f.confidence())).append('\n')
          .append("audiences=").append(f.audiences()).append('\n')
          .append("evidenceSql=").append(f.evidenceSql()).append('\n');
        return sb.toString();
    }
}
```

- [ ] **Step 4: Extend ModelClient for tool calls, keeping it SDK-agnostic**

Add to `Tool`: `default ToolSpec spec() { return new ToolSpec(name(), description(), parameters()); }`

`service/src/main/java/com/signaldesk/model/ToolSpec.java`:

```java
package com.signaldesk.model;

import java.util.Map;

/** What the model is told a tool can do. Deliberately not the Tool itself, so the
 *  model package never depends on the tool implementations. */
public record ToolSpec(String name, String description, Map<String, String> parameters) {}
```

`service/src/main/java/com/signaldesk/model/ModelReply.java`:

```java
package com.signaldesk.model;

import java.util.Map;

public sealed interface ModelReply {

    record Text(String content) implements ModelReply {}

    record ToolCall(String name, Map<String, String> args) implements ModelReply {}
}
```

Add to `ModelClient`:

```java
    /** One turn, with tools offered. Returns either prose or a single tool call. */
    ModelReply completeWithTools(List<ChatMessage> messages, List<ToolSpec> tools);
```

Implement it in `SarvamClient` using the SDK's native `tools` array and reading
`finish_reason == "tool_calls"` — the capability verified in preflight.

**Adding a method to `ModelClient` breaks every existing implementor at compile
time, and one of them is eight tasks old.** In the same commit, add
`completeWithTools` to:

- `SarvamClient` (the real implementation)
- `SarvamComposerTest.StubModel` — return `new ModelReply.Text(reply)` so the
  existing composer tests keep passing unchanged

Run `./scripts/mvn.sh -q test` before writing any tool tests. A green suite here
proves the interface change landed cleanly; a red one is a compile error, not a
logic bug, and it is faster to fix before the new tests exist.

**If the SDK's tool-call surface fights back**, do not spend more than twenty
minutes: fall back to a text protocol driven entirely by the system prompt —
instruct the model to reply with exactly `CALL <tool_name> {"arg":"value"}` or
`ANSWER <text>`, and parse that in `SarvamClient`. Note in the deck which of the
two you shipped. Saying "real tool calling" on stage while running a text
protocol is a claim that will not survive a follow-up question, and the honest
version is still a strong answer: the tools are validated and the database is
unreachable except through them either way.

- [ ] **Step 5: Write the interrogator and the endpoint**

`service/src/main/java/com/signaldesk/model/Interrogator.java`:

```java
package com.signaldesk.model;

import com.signaldesk.agent.FindingStore;
import com.signaldesk.agent.NarrativeValidator;
import com.signaldesk.agent.SweepRun;
import com.signaldesk.model.tools.Tool;
import com.signaldesk.model.tools.ToolCallTrace;
import com.signaldesk.model.tools.ToolRegistry;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Answers an open question through validated tools only. The database is
 * unreachable from here except through ToolRegistry, and the answer is checked
 * against the run's findings before it is returned — the same guard
 * SarvamComposer applies to the brief.
 */
@Component
public class Interrogator {

    /** Hard bound. An unbounded tool loop against a 60 req/min tier is how a demo
     *  runs out of credits mid-question. */
    public static final int MAX_TOOL_CALLS = 4;

    private static final Logger log = LoggerFactory.getLogger(Interrogator.class);

    private static final String SYSTEM = """
            You answer questions about enterprise commute operations for a transport
            manager. You have no data of your own. Use the tools to read metrics and
            findings.

            Rules:
            - Never state a figure you did not receive from a tool. Do not estimate,
              extrapolate, or compute anything yourself.
            - Cite the reference point behind every figure you quote.
            - When you have enough, answer in under 120 words.
            - If a tool refuses an argument, read the valid values it names and retry
              with one of them. Do not invent argument values.
            """;

    private final ModelClient model;
    private final ToolRegistry tools;
    private final FindingStore store;

    public Interrogator(ModelClient model, ToolRegistry tools, FindingStore store) {
        this.model = model;
        this.tools = tools;
        this.store = store;
    }

    public record Answer(String answer, List<ToolCallTrace> trace) {}

    public Answer ask(String runId, String question) {
        List<ToolCallTrace> trace = new ArrayList<>();
        List<ChatMessage> messages = new ArrayList<>();
        messages.add(new ChatMessage("system", SYSTEM));
        messages.add(new ChatMessage("user", "Run: " + runId + "\nQuestion: " + question));

        List<ToolSpec> specs = tools.all().stream().map(Tool::spec).toList();

        for (int i = 0; i < MAX_TOOL_CALLS; i++) {
            ModelReply reply;
            try {
                reply = model.completeWithTools(messages, specs);
            } catch (RuntimeException e) {
                log.warn("model unreachable during interrogation: {}", e.getMessage());
                return new Answer(
                        "The model is unreachable, so this question cannot be answered right now. "
                                + "The findings and their evidence are still on the console.",
                        trace);
            }

            if (reply instanceof ModelReply.Text text) {
                return new Answer(validated(text.content(), runId, trace), trace);
            }

            ModelReply.ToolCall call = (ModelReply.ToolCall) reply;
            Tool tool = tools.byName(call.name());
            String result = tool == null
                    ? "unknown tool '" + call.name() + "'; available tools are "
                            + tools.all().stream().map(Tool::name).toList()
                    : safeInvoke(tool, call);
            trace.add(new ToolCallTrace(call.name(), call.args(), result));
            messages.add(new ChatMessage("user", "Tool " + call.name() + " returned:\n" + result));
        }

        // Budget exhausted: answer from what was gathered rather than looping.
        try {
            String forced = model.complete(withFinalInstruction(messages));
            return new Answer(validated(forced, runId, trace), trace);
        } catch (RuntimeException e) {
            return new Answer("Could not reach a settled answer within "
                    + MAX_TOOL_CALLS + " tool calls.", trace);
        }
    }

    private static List<ChatMessage> withFinalInstruction(List<ChatMessage> messages) {
        List<ChatMessage> out = new ArrayList<>(messages);
        out.add(new ChatMessage("user",
                "Answer now, using only the tool results above. Do not request another tool."));
        return out;
    }

    private static String safeInvoke(Tool tool, ModelReply.ToolCall call) {
        try {
            return tool.invoke(call.args());
        } catch (RuntimeException e) {
            return "tool " + tool.name() + " failed: " + e.getMessage();
        }
    }

    /** The same rejection the brief gets: an invented figure never reaches a screen. */
    private String validated(String answer, String runId, List<ToolCallTrace> trace) {
        Optional<SweepRun> run = "latest".equals(runId) ? store.latest() : store.get(runId);
        if (run.isEmpty()) {
            return answer;
        }
        Optional<String> offending = NarrativeValidator.validate(answer, run.get());
        if (offending.isPresent()) {
            log.warn("interrogation answer rejected: figure {} is not in the findings",
                    offending.get());
            return "That answer contained a figure (" + offending.get() + ") that is not in the "
                    + "findings, so it has been withheld. The tool results below are the "
                    + "verified numbers.";
        }
        return answer;
    }
}
```

Withholding rather than silently passing the answer through is the point: the
trace is still returned, so the user sees the real numbers even when the prose is
rejected.

`service/src/main/java/com/signaldesk/api/AskController.java`:

```java
package com.signaldesk.api;

import com.signaldesk.model.Interrogator;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@CrossOrigin
public class AskController {

    public record AskRequest(String runId, String question) {}

    private final Interrogator interrogator;

    public AskController(Interrogator interrogator) {
        this.interrogator = interrogator;
    }

    @PostMapping("/ask")
    public Interrogator.Answer ask(@RequestBody AskRequest request) {
        String runId = request.runId() == null || request.runId().isBlank()
                ? "latest" : request.runId();
        return interrogator.ask(runId, request.question());
    }
}
```

- [ ] **Step 6: Write the interrogator tests**

`service/src/test/java/com/signaldesk/model/InterrogatorTest.java`:

```java
package com.signaldesk.model;

import static org.assertj.core.api.Assertions.assertThat;

import com.signaldesk.agent.FindingStore;
import com.signaldesk.agent.SweepRun;
import com.signaldesk.ingest.Feed;
import com.signaldesk.ingest.FeedHealth;
import com.signaldesk.model.tools.Tool;
import com.signaldesk.model.tools.ToolRegistry;
import com.signaldesk.registry.Dimension;
import com.signaldesk.registry.ReferenceKind;
import com.signaldesk.registry.Slice;
import com.signaldesk.registry.Window;
import com.signaldesk.verdict.Audience;
import com.signaldesk.verdict.Cause;
import com.signaldesk.verdict.Finding;
import com.signaldesk.verdict.Reference;
import com.signaldesk.verdict.Tier;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class InterrogatorTest {

    private final Window window = Window.weekEnding(10 * Window.WEEK_MS);
    private FindingStore store;

    /** Replays a scripted sequence of replies, recording what it was asked. */
    static class ScriptedModel implements ModelClient {
        final Deque<ModelReply> script = new ArrayDeque<>();
        final List<List<ChatMessage>> calls = new java.util.ArrayList<>();
        boolean throwOnCall;
        String forcedFinal = "No settled answer.";

        @Override public String complete(List<ChatMessage> messages) {
            if (throwOnCall) {
                throw new RuntimeException("model unreachable");
            }
            calls.add(List.copyOf(messages));
            return forcedFinal;
        }

        @Override public ModelReply completeWithTools(List<ChatMessage> messages,
                                                      List<ToolSpec> tools) {
            if (throwOnCall) {
                throw new RuntimeException("model unreachable");
            }
            calls.add(List.copyOf(messages));
            return script.isEmpty() ? new ModelReply.Text("No answer.") : script.poll();
        }

        @Override public boolean supportsToolCalling() { return true; }
    }

    /** A tool that records its invocations, so "did it actually call it" is checkable. */
    static class SpyTool implements Tool {
        final List<Map<String, String>> invocations = new java.util.ArrayList<>();
        String result = "vendor_ota vendor V07 observed=61.40% | peer median=89.20";

        @Override public String name() { return "list_findings"; }
        @Override public String description() { return "spy"; }
        @Override public Map<String, String> parameters() { return Map.of("runId", "id"); }

        @Override public String invoke(Map<String, String> args) {
            invocations.add(args);
            return result;
        }
    }

    @BeforeEach
    void seedOneKnownRun() {
        Finding f = new Finding("f1", "vendor_ota", new Slice(Dimension.VENDOR, "V07"), window,
                61.40, List.of(new Reference(ReferenceKind.PEER, 89.20, "peer median")),
                Tier.BREACH, Cause.PEER_LAGGARD, 27.80, 0.97,
                Set.of(Audience.FACILITIES_HEAD), "SELECT 1");
        store = new FindingStore();
        store.put(new SweepRun("run-1", window, List.of(f),
                Map.of(Feed.TRIPS, FeedHealth.of(Feed.TRIPS, 100, 0, 0, 0)), window.endMs()));
    }

    @Test
    void invokesTheToolTheModelNamedAndRecordsItInTheTrace() {
        SpyTool spy = new SpyTool();
        ScriptedModel model = new ScriptedModel();
        model.script.add(new ModelReply.ToolCall("list_findings", Map.of("runId", "run-1")));
        model.script.add(new ModelReply.Text("V07 is at 61.40% against a peer median of 89.20%."));

        Interrogator.Answer answer = new Interrogator(model, new ToolRegistry(List.of(spy)), store)
                .ask("run-1", "Why is V07 flagged?");

        assertThat(spy.invocations).hasSize(1);
        assertThat(answer.trace()).singleElement().satisfies(t -> {
            assertThat(t.tool()).isEqualTo("list_findings");
            assertThat(t.result()).contains("61.40");
        });
        assertThat(answer.answer()).contains("61.40");
    }

    @Test
    void refusesAnUnknownToolWithoutInvokingAnything() {
        SpyTool spy = new SpyTool();
        ScriptedModel model = new ScriptedModel();
        model.script.add(new ModelReply.ToolCall("run_sql", Map.of("sql", "DROP TABLE trips")));
        model.script.add(new ModelReply.Text("I cannot do that."));

        Interrogator.Answer answer = new Interrogator(model, new ToolRegistry(List.of(spy)), store)
                .ask("run-1", "Just run this query");

        assertThat(spy.invocations).as("there is no run_sql tool and nothing else ran").isEmpty();
        assertThat(answer.trace()).singleElement().satisfies(t ->
                assertThat(t.result()).containsIgnoringCase("unknown tool"));
    }

    @Test
    void stopsAfterFourToolCallsRatherThanLoopingForever() {
        SpyTool spy = new SpyTool();
        ScriptedModel model = new ScriptedModel();
        for (int i = 0; i < 10; i++) {
            model.script.add(new ModelReply.ToolCall("list_findings", Map.of("runId", "run-1")));
        }

        Interrogator.Answer answer = new Interrogator(model, new ToolRegistry(List.of(spy)), store)
                .ask("run-1", "Loop forever");

        assertThat(spy.invocations).hasSize(Interrogator.MAX_TOOL_CALLS);
        assertThat(answer.trace()).hasSize(Interrogator.MAX_TOOL_CALLS);
    }

    @Test
    void withholdsAnAnswerContainingAFigureNoToolReturned() {
        // The dangerous case, and the reason the interrogation panel is trustworthy:
        // the same validator that guards the brief guards the answer.
        SpyTool spy = new SpyTool();
        ScriptedModel model = new ScriptedModel();
        model.script.add(new ModelReply.ToolCall("list_findings", Map.of("runId", "run-1")));
        model.script.add(new ModelReply.Text("V07 is at 61.40%, down from 94.30% last month."));

        Interrogator.Answer answer = new Interrogator(model, new ToolRegistry(List.of(spy)), store)
                .ask("run-1", "Why is V07 flagged?");

        assertThat(answer.answer()).doesNotContain("94.30").containsIgnoringCase("withheld");
        assertThat(answer.trace()).as("the verified numbers are still shown").isNotEmpty();
    }

    @Test
    void aModelOutageReturnsAPlainRefusalRatherThanAnException() {
        ScriptedModel model = new ScriptedModel();
        model.throwOnCall = true;

        Interrogator.Answer answer =
                new Interrogator(model, new ToolRegistry(List.of(new SpyTool())), store)
                        .ask("run-1", "Why is V07 flagged?");

        assertThat(answer.answer()).containsIgnoringCase("unreachable");
        assertThat(answer.trace()).isEmpty();
    }

    @Test
    void aToolThatThrowsIsReportedInTheTraceRatherThanFailingTheRequest() {
        Tool exploding = new Tool() {
            @Override public String name() { return "list_findings"; }
            @Override public String description() { return "boom"; }
            @Override public Map<String, String> parameters() { return Map.of(); }
            @Override public String invoke(Map<String, String> args) {
                throw new IllegalStateException("connection closed");
            }
        };
        ScriptedModel model = new ScriptedModel();
        model.script.add(new ModelReply.ToolCall("list_findings", Map.of()));
        model.script.add(new ModelReply.Text("I could not read the findings."));

        Interrogator.Answer answer = new Interrogator(model, new ToolRegistry(List.of(exploding)),
                store).ask("run-1", "Why is V07 flagged?");

        assertThat(answer.trace()).singleElement().satisfies(t ->
                assertThat(t.result()).contains("connection closed"));
    }
}
```

- [ ] **Step 7: Break-it-to-prove-it**

Change `MAX_TOOL_CALLS` to 100, rerun. Expected:
`stopsAfterFourToolCallsRatherThanLoopingForever` FAILS. Restore.

Delete the `validated(...)` wrapper so the answer passes through raw, rerun.
Expected: `withholdsAnAnswerContainingAFigureNoToolReturned` FAILS. Restore.

Remove the `tool == null` branch so an unknown name reaches `tool.invoke`, rerun.
Expected: `refusesAnUnknownToolWithoutInvokingAnything` FAILS with an NPE.
Restore.

- [ ] **Step 8: Run everything**

Run: `./scripts/mvn.sh -q test`
Expected: PASS, including `InvariantTest.noToolExposesRawSqlExecution`.

- [ ] **Step 9: Ask it a real question**

```bash
curl -s -X POST http://localhost:8080/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"runId":"latest","question":"Why is vendor V07 flagged?"}' | python3 -m json.tool
```
Expected: an answer naming V07's observed value and its peer median, plus a trace
showing `list_findings` and/or `explain_finding` being called. **The trace is the
feature** — it is what makes the reasoning visible rather than asserted.

- [ ] **Step 10: Commit**

```bash
git add service
git commit -m "feat(model): four validated tools and an interrogation endpoint with a visible trace"
```

---

### Task 23: Console — the interrogation panel (~0 h 45)

**Files:**
- Create: `console/src/api/types.ts` additions (`AskResponse`, `TraceEntry`)
- Create: `console/src/components/ToolTrace.tsx`, `InterrogationPanel.tsx`
- Modify: `console/src/api/client.ts` (`askQuestion`)
- Modify: `console/src/App.tsx` (mount the panel)
- Test: `console/src/components/__tests__/InterrogationPanel.test.tsx`

**Interfaces:**
- Consumes: `POST /api/ask` → `{ answer, trace: [{ tool, args, result }] }`.
- Produces: `askQuestion(runId, question)` in `client.ts`.

**The trace is the feature.** "Why is this vendor flagged?" answered through the
same registry, with the tool calls shown, is what makes the reasoning visible
rather than asserted — and it is what separates this from a chat box over a
database.

- [ ] **Step 1: Add the types and the client call**

Append to `console/src/api/types.ts`:

```ts
export interface TraceEntry {
  tool: string
  args: Record<string, string>
  result: string
}

export interface AskResponse {
  answer: string
  trace: TraceEntry[]
}
```

Append to `console/src/api/client.ts`:

```ts
export const askQuestion = (runId: string, question: string) =>
  json<AskResponse>('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ runId, question }),
  })
```

Add `AskResponse` to the existing `import type` line at the top of `client.ts`.

- [ ] **Step 2: Write the failing tests**

`console/src/components/__tests__/InterrogationPanel.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { InterrogationPanel } from '../InterrogationPanel'
import type { AskResponse } from '../../api/types'

const answer: AskResponse = {
  answer: 'V07 is at 61.40% against a peer median of 89.20%. Move volume off it.',
  trace: [
    { tool: 'list_findings', args: { runId: 'run-1', tier: 'BREACH' },
      result: 'f1 vendor_ota [vendor V07] BREACH observed=61.40' },
    { tool: 'explain_finding', args: { findingId: 'f1' },
      result: 'evidenceSql=SELECT 100.0 * sum(...) FROM trips t' },
  ],
}

function mockAsk(response: AskResponse | Error, delayMs = 0) {
  vi.stubGlobal('fetch', vi.fn(() =>
    new Promise((resolve, reject) =>
      setTimeout(() => {
        if (response instanceof Error) {
          resolve({ ok: false, status: 500, json: async () => ({}) })
        } else {
          resolve({ ok: true, status: 200, json: async () => response })
        }
      }, delayMs),
    ),
  ))
}

afterEach(() => vi.unstubAllGlobals())

describe('InterrogationPanel', () => {
  it('shows the answer and every tool call that produced it', async () => {
    mockAsk(answer)
    render(<InterrogationPanel runId="run-1" />)

    await userEvent.type(screen.getByLabelText(/ask/i), 'Why is V07 flagged?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    await waitFor(() => expect(screen.getByText(/61\.40%/)).toBeInTheDocument())
    expect(screen.getByText(/list_findings/)).toBeInTheDocument()
    expect(screen.getByText(/explain_finding/)).toBeInTheDocument()
  })

  it('shows the arguments and the result for each call, not just the tool name', async () => {
    mockAsk(answer)
    render(<InterrogationPanel runId="run-1" />)

    await userEvent.type(screen.getByLabelText(/ask/i), 'Why?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))
    await waitFor(() => expect(screen.getByText(/list_findings/)).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /show the tool calls/i }))

    expect(screen.getByText(/findingId/)).toBeInTheDocument()
    expect(screen.getByText(/evidenceSql/)).toBeInTheDocument()
  })

  it('shows a pending state while the model is working', async () => {
    mockAsk(answer, 50)
    render(<InterrogationPanel runId="run-1" />)

    await userEvent.type(screen.getByLabelText(/ask/i), 'Why?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(screen.getByRole('button', { name: /thinking/i })).toBeDisabled()
    await waitFor(() => expect(screen.getByText(/61\.40%/)).toBeInTheDocument())
  })

  it('surfaces an error plainly instead of rendering an empty answer', async () => {
    mockAsk(new Error('boom'))
    render(<InterrogationPanel runId="run-1" />)

    await userEvent.type(screen.getByLabelText(/ask/i), 'Why?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/failed|500/i))
  })

  it('refuses to submit an empty question rather than calling the model', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    render(<InterrogationPanel runId="run-1" />)

    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('renders a withheld answer as-is, so a rejected figure is visible as a refusal', async () => {
    // The service withholds an answer containing an invented figure and still
    // returns the trace. The panel must not hide that.
    mockAsk({
      answer: 'That answer contained a figure (94.30) that is not in the findings, '
        + 'so it has been withheld.',
      trace: answer.trace,
    })
    render(<InterrogationPanel runId="run-1" />)

    await userEvent.type(screen.getByLabelText(/ask/i), 'Why?')
    await userEvent.click(screen.getByRole('button', { name: /ask/i }))

    await waitFor(() => expect(screen.getByText(/withheld/)).toBeInTheDocument())
    expect(screen.getByText(/list_findings/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd console && npm test -- InterrogationPanel`
Expected: FAIL — `Failed to resolve import "../InterrogationPanel"`.

- [ ] **Step 4: Write ToolTrace**

`console/src/components/ToolTrace.tsx`:

```tsx
import { useState } from 'react'
import type { TraceEntry } from '../api/types'

/**
 * The reasoning, shown rather than asserted. Collapsed by default so the answer
 * leads, expandable because "which tools did it actually call" is the question a
 * sceptical reader asks next.
 */
export function ToolTrace({ trace }: { trace: TraceEntry[] }) {
  const [open, setOpen] = useState(false)
  if (trace.length === 0) {
    return null
  }
  return (
    <div style={{ marginTop: 12 }}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{ background: 'none', border: 'none', padding: 0, font: 'inherit',
                 color: '#5b5bd6', cursor: 'pointer' }}
      >
        {open ? 'Hide' : 'Show'} the tool calls ({trace.length})
      </button>
      <ol style={{ fontSize: 13, marginTop: 8, paddingLeft: 20 }}>
        {trace.map((t, i) => (
          <li key={i} style={{ marginBottom: 8 }}>
            <code style={{ fontWeight: 600 }}>{t.tool}</code>
            {open && (
              <>
                <div style={{ color: '#52525b' }}>
                  {Object.entries(t.args).map(([k, v]) => `${k}=${v}`).join(', ') || 'no arguments'}
                </div>
                <pre style={{ whiteSpace: 'pre-wrap', overflowX: 'auto', background: '#f6f6f7',
                              padding: 8, marginTop: 4, fontSize: 12 }}>
                  {t.result}
                </pre>
              </>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}
```

The tool *names* render whether or not the panel is expanded — that is what the
first test asserts, and it means a glance at the answer already shows it came
from the registry rather than from the model's memory.

- [ ] **Step 5: Write InterrogationPanel**

`console/src/components/InterrogationPanel.tsx`:

```tsx
import { useState } from 'react'
import { askQuestion } from '../api/client'
import type { AskResponse } from '../api/types'
import { ToolTrace } from './ToolTrace'

const SUGGESTIONS = [
  'Why is vendor V07 flagged?',
  'Which site has the worst on-time arrival this week?',
  'How confident are you in the experience score?',
]

export function InterrogationPanel({ runId }: { runId: string }) {
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [response, setResponse] = useState<AskResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const ask = async (q: string) => {
    if (!q.trim()) {
      return
    }
    setAsking(true)
    setError(null)
    setResponse(null)
    try {
      setResponse(await askQuestion(runId, q.trim()))
    } catch (e) {
      setError(String(e))
    } finally {
      setAsking(false)
    }
  }

  return (
    <section style={{ marginTop: 24 }}>
      <h2 style={{ fontSize: 15 }}>Ask it</h2>
      <form
        onSubmit={(e) => { e.preventDefault(); ask(question) }}
        style={{ display: 'flex', gap: 8 }}
      >
        <label htmlFor="question" style={{ position: 'absolute', left: -9999 }}>
          Ask a question about this sweep
        </label>
        <input
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Why is vendor V07 flagged?"
          style={{ flex: 1, padding: '6px 8px', font: 'inherit' }}
        />
        <button type="submit" disabled={asking}>
          {asking ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => { setQuestion(s); ask(s) }}
            disabled={asking}
            style={{ fontSize: 12, background: '#f6f6f7', border: '1px solid #e4e4e7',
                     borderRadius: 12, padding: '2px 10px', cursor: 'pointer' }}
          >
            {s}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" style={{ color: '#b3261e' }}>
          The question could not be answered: {error}
        </p>
      )}

      {response && (
        <div style={{ marginTop: 12 }}>
          <p style={{ margin: 0, lineHeight: 1.5 }}>{response.answer}</p>
          <ToolTrace trace={response.trace} />
        </div>
      )}
    </section>
  )
}
```

The three suggested questions are there for the demo: a judge should not have to
think of a question, and the first one is the V07 narrative the whole fixture was
built to produce.

- [ ] **Step 6: Mount it in App.tsx**

`App.tsx` already holds `runId` from Task 18's brief fetch. Render
`<InterrogationPanel runId={runId} />` below the findings list and above the
brief preview, guarded so it only mounts once a `runId` exists:

```tsx
      {runId && <InterrogationPanel runId={runId} />}
```

- [ ] **Step 7: Run the console tests**

Run: `cd console && npm test`
Expected: PASS, 16 tests across all four component test files.

- [ ] **Step 8: Ask it a real question in the browser**

With the service running and `SARVAM_API_KEY` set, open the console and click the
"Why is vendor V07 flagged?" suggestion.

Expected: an answer naming V07's observed on-time share and its peer median, with
`list_findings` and `explain_finding` visible beneath it, expandable to the
arguments and the raw tool output including `evidenceSql`.

**Then ask something the tools cannot answer** — "what will OTA be next month?" —
and confirm the answer declines rather than inventing a forecast. Forecasting is
explicitly out of scope (§2.2), and a judge asking exactly this is likely.

- [ ] **Step 9: Break-it-to-prove-it**

Remove the `if (!q.trim()) return` guard, rerun. Expected:
`refuses to submit an empty question rather than calling the model` FAILS.
Restore.

Move the tool-name `<code>` inside the `{open && ...}` block, rerun. Expected:
`shows the answer and every tool call that produced it` FAILS. Restore.

- [ ] **Step 10: Commit**

```bash
git add console
git commit -m "feat(console): interrogation panel showing the answer and its tool trace"
```

---

### Task 24: Deck, README, diagram, and one offline rehearsal (~1 h 30 — RESERVED)

**Start this no later than 1 h 30 before the deadline, whatever is unfinished.**
These are scored deliverables. An unpolished feature costs a fraction of what a
missing deck costs.

**Files:**
- Modify: `README.md` — replace the "no application code yet, and no design spec"
  section, which is now false
- Modify: `AGENTS.md` — same, its "Current state" section
- Create: `docs/architecture.md` with the four-layer diagram
- Create: `docs/demo-script.md`

- [ ] **Step 1: Correct the two stale documents first (~10 min)**

`README.md` and `AGENTS.md` both say "No application code. No design spec." Both
were true when written and are now wrong. A judge or teammate reading them will
be misled. Replace with what exists: the spec, this plan, the service, the
console, and the current active-metric list.

- [ ] **Step 2: Write the architecture document (~20 min)**

Carry over the four-layer diagram from `PROPOSAL.md` §3, corrected to what was
actually built — including any Phase 2 task that did not land. **Do not diagram
an unbuilt feature.** Add the one paragraph a judge will ask for: why an embedded
database, answered on latency and tolerant ingestion, with the Athena 2-second
floor as the specific number.

- [ ] **Step 3: Write the demo script (~20 min)**

Six beats, timed, with the exact commands:

1. "It swept without being asked" — point at the startup log line
2. "It found this" — the ranked console, top finding is V07
3. "Here is where the number came from" — expand the row, show `evidenceSql`
4. "Here is what it could not read" — the feed-health strip, quarantined count
5. "It sent this" — the Slack message, already in the channel
6. "And it will defend it" — the interrogation panel, with the trace visible

If a step's feature was cut, delete the beat. A script promising something the
build does not do is worse than a shorter script.

- [ ] **Step 4: Rehearse it once, fully offline (~20 min)**

Turn the WiFi **off**. Run the whole six-beat script end to end.

Expected: beats 1–4 work completely offline. Beats 5 and 6 need the network — so
the script must say so, and the Slack message from an earlier online run must
already be in the channel as the fallback. **Assumption 5 says every demo path
works offline; this is where that gets tested rather than believed.**

Fix whatever breaks. This rehearsal is the single highest-value 20 minutes in
Phase 2.

- [ ] **Step 5: Warm the deployed URLs and confirm the secret hygiene (~10 min)**

Both services were deployed and verified in Tasks 16 and 19 — **both on Render**,
not the spec's Render/Vercel split — so this step is verification and warming, not
a first attempt. The deck must say Render for both.

**Hit the Render URL to warm the JVM** a few minutes before presenting — cold
start is 30–90 seconds and the free tier spins down after 15 minutes idle. Then
load the console once and confirm it still reaches the service (a redeploy resets
nothing, but a stale `SIGNALDESK_CORS_ORIGINS` value would):

```bash
curl -s -o /dev/null -w 'service %{http_code} in %{time_total}s\n' \
  https://<your-service>.onrender.com/api/health
curl -s -o /dev/null -w 'console %{http_code}\n' \
  https://signal-desk-console.onrender.com/
```

The scored demo still runs on the laptop, and the deck should say so in one
sentence rather than leaving a judge to wonder why there is a URL at all.

Then confirm nothing credential-shaped ever reached the repo:

```bash
git log -p | grep -iE 'hooks\.slack\.com/services/[A-Z0-9]{5,}|sk-[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9]{10,}' \
  | grep -v REPLACE
```
Expected: no output. Also check the deck and any screenshot in it. A Slack
webhook URL is a credential; a screenshot showing one has leaked it.

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md docs
git commit -m "docs: architecture, demo script, and correct the stale current-state sections"
```

---

## Self-review — done at authoring time, recorded here

**Spec coverage.** Every numbered item in §2.1 maps to a task: (1) Task 3,
(2) Task 4, (3) Task 5, (4) Tasks 7–8, (5) Task 9, (6) Tasks 12–13, (7) Tasks 11
and 14, (8) Tasks 17–18, (9) Tasks 22–23, (10) Task 21. §3's dataset is Task 2,
§5.4's references are Task 6, §6.3's calibration requirement is Task 10, §10's
required-tests table is covered layer by layer, and §11's deployment is Tasks 16
and 19 with warming and verification in Task 24 Step 5. Nothing in §2.2's
out-of-scope list has a task, which is the intent.

**Deployment was originally under-planned, and that gap was closed on request.**
The first draft satisfied §11 with a single step inside the deck task. That is
thin for 20% of the score and it defers the riskiest infrastructure to the worst
possible moment. Tasks 16 and 19 now own it: a root `Dockerfile` (the build
context needs both `service/` and `data/`), a real `/api/health` that reports
degraded when no metrics are active, `${PORT:8080}` because Render injects the
port, configurable CORS replacing the bare `@CrossOrigin` annotations, one Render
blueprint describing **both** services with every secret `sync: false`, an SPA
rewrite route, and an end-to-end check of the deployed pair. Three of those were
latent defects a real deploy would have found and a laptop demo never would: the
hardcoded `server.port`, the permissive `@CrossOrigin`, and a base URL that breaks
on a trailing slash. Spec §11's Vercel split is superseded at the human partner's
direction — both surfaces are on Render, and the deck must say so.

**Two gaps found and closed while reviewing.** §6.3's calibration was originally
folded into Task 7 and would have run against provisional data; it is now Task
10, with the re-pin duty repeated in Tasks 20 and 19 where new metrics move the
distribution. §9.2's brief-preview surface had no endpoint behind it; Task 18
adds `GET /api/runs/{runId}/brief`.

**Type consistency.** `Finding`'s twelve components are constructed identically
in `VerdictEngine`, both test fixtures, and `FindingDto.from`. `Slice.label()`,
`Window.label()`, `Metric.unit()`, `Tier`, `Cause` and `Audience` names are used
consistently across the Java and the TypeScript. `MetricRepository`'s four
methods are implemented by `DuckDbMetricRepository` and by both test stubs.
`Composer.compose(SweepRun, Audience)` has one signature everywhere.

**Tasks 22 and 21 were filled in after the scope decision.** They were first
drafted thin — `GetMetricTool` in full, the other three tools and the whole
console panel as prose — on the reasoning that they were the likeliest cuts and
200 lines of code for work that would not happen was a poor use of the hour
before the build. The decision to extend the time rather than strip scope removed
that reasoning, so both tasks now carry the same full code and test bodies as
everything before them: all four tools, `ModelReply`/`ToolSpec`, the bounded
`Interrogator` with its validation guard, `ToolTrace`, `InterrogationPanel`, and
both test files.

**One thing genuinely left to the implementer.** `SarvamClient.completeWithTools`
is specified by its interface and its behaviour, not by SDK-specific code, because
the OpenAI Java SDK's tool-call surface moves between versions and the exact
method names cannot be pinned honestly from here. Task 22 Step 4 gives the escape
hatch — a prompt-driven `CALL`/`ANSWER` text protocol — with a twenty-minute
budget and an instruction to say in the deck which of the two shipped. Everything
above that method is fully specified and fully stubbed in the tests, so the
uncertainty is contained to one method body.

**A note on the extended timebox.** With nothing being cut, the tail tasks now
carry real weight: Task 21's vernacular pipeline and Tasks 22–23's panel are no
longer optional flourishes, so their break-it-to-prove-it steps matter as much as
Task 7's. The checkpoint at Task 11 is now purely a correctness gate — treat a
red gate as a reason to stop and fix, not as slack to spend.
