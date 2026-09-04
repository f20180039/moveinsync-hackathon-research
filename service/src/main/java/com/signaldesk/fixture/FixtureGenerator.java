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
     * All six writers below share this single Random draw-for-draw: inserting
     * or removing any nextInt/nextDouble call anywhere in this sequence shifts
     * every subsequent draw and changes the committed fixture's bytes. The pin
     * test (theCommittedFixtureMatchesWhatTheGeneratorProducesNow) will catch
     * it, but expect a byte diff across every remaining feed, not just the one
     * you touched.
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
        System.out.println("fixture written to " + out.toAbsolutePath().normalize() + " (seed " + SEED + ")");
    }
}
