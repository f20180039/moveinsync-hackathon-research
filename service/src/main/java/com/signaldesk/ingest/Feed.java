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
