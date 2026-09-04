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
