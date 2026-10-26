"""ELM timers, merged by Fusion's Celery configuration."""

BEAT_SCHEDULE = {
    "leave.process-sla": {
        "task": "leave.process_sla",
        "schedule": 900.0,
        "options": {"expires": 840},
    },
    "leave.year-end-boundary": {
        "task": "leave.process_year_end_boundary",
        "schedule": 86400.0,
        "options": {"expires": 82800},
    },
}

TASK_ROUTES = {
    "leave.process_sla": {"queue": "default"},
    "leave.process_year_end_boundary": {"queue": "default"},
}
