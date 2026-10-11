"""Single place for all tunables: zones, weights, thresholds, bands."""
ZONES = {  # fictional city; "Central District" plays the role of Zone A
    "Central District": (26.9124, 75.7873), "North District": (26.9524, 75.7873),
    "South District": (26.8724, 75.7873), "East District": (26.9124, 75.8373),
    "West District": (26.9124, 75.7373), "Industrial Zone": (26.8824, 75.8373),
    "University Zone": (26.9424, 75.7373), "Residential Zone": (26.8824, 75.7373),
}
# source: (default event_type, value field, typical baseline)
SOURCES = {"weather": ("rainfall", "rainfall", 2.0), "traffic": ("traffic_incident", "incident_count", 7.0),
           "complaints": ("complaint", "complaint_count", 8.0), "transit": ("transit_delay", "delay_minutes", 6.0),
           "air_quality": ("aqi", "aqi", 80.0), "utilities": ("outage", "affected_customers", 200.0)}
COUNTS = {"weather": 100, "traffic": 100, "complaints": 150, "transit": 80, "air_quality": 80, "utilities": 50}
WEIGHTS = {"weather": .25, "traffic": .25, "complaints": .20, "transit": .15, "air_quality": .10, "utilities": .05}
THRESHOLDS = [("CRITICAL", 250), ("HIGH", 150), ("MEDIUM", 100), ("LOW", 50)]  # % above baseline
BANDS = [(25, "NORMAL"), (50, "WATCH"), (75, "ELEVATED"), (100, "CRITICAL")]
WINDOW_MIN = 30
SCORE_FULL_PCT = 250  # % change that maps to a full 100 component score
