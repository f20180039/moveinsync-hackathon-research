package com.signaldesk.fixture;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.signaldesk.ingest.Feed;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
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

        List<String> pings = Files.readAllLines(dir.resolve(Feed.GPS_PINGS.fileName()));
        Map<String, Long> perTrip = pings.stream().skip(1)
                .collect(Collectors.groupingBy(r -> r.split(",")[0], Collectors.counting()));
        long gapped = perTrip.values().stream().filter(n -> n < 20).count();
        assertThat(gapped / (double) perTrip.size()).as("gapped GPS traces").isBetween(0.09, 0.16);

        List<String> roster = Files.readAllLines(dir.resolve(Feed.ROSTER.fileName()));
        long orphan = roster.stream().skip(1).filter(r -> r.startsWith("E9")).count();
        assertThat(orphan / (double) (roster.size() - 1)).as("orphan roster").isBetween(0.03, 0.07);
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
}
