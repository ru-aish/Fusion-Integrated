"""What the server tells the shell about this module (ADR-0010)."""

MODULE = {
    "code": "leave_cell",
    "label": "Leave Management",
    "icon": "Calendar",
    "base_path": "/leave",
    "nav_section": "HR",
    "sort_order": 20,
    "status": "active",
}

NAV_ITEMS = [
    {
        "code": "leave_cell.balances",
        "label": "Leave Balances",
        "icon": "ClipboardList",
        "to": "/leave/balances",
        "required_permission": "leave_cell.balances.view",
        "sort_order": 5,
    },
    {
        "code": "leave_cell.requests",
        "label": "Leave Requests",
        "icon": "CalendarCheck",
        "to": "/leave/requests",
        "required_permission": "leave_cell.requests.view",
        "sort_order": 10,
    },
    {
        "code": "leave_cell.inbox",
        "label": "Leave Approvals",
        "icon": "Inbox",
        "to": "/leave/inbox",
        "required_permission": "leave_cell.tasks.view",
        "sort_order": 15,
    },
]

PERMISSIONS = [
    ("leave_cell.balances.view", "View leave balances"),
    ("leave_cell.requests.view", "View own leave requests"),
    ("leave_cell.requests.create", "Create leave requests"),
    ("leave_cell.tasks.view", "View assigned leave tasks"),
    ("leave_cell.tasks.act", "Act on assigned leave tasks"),
    ("leave_cell.configuration.manage", "Manage authoritative leave configuration"),
]

ROLE_GRANTS = {
    "employee": [
        "leave_cell.balances.view",
        "leave_cell.requests.view",
        "leave_cell.requests.create",
    ],
    "hr": [
        "leave_cell.balances.view",
        "leave_cell.requests.view",
        "leave_cell.requests.create",
        "leave_cell.tasks.view",
        "leave_cell.tasks.act",
        "leave_cell.configuration.manage",
    ],
    "unit_head": ["leave_cell.tasks.view", "leave_cell.tasks.act"],
    "sanctioning_authority": ["leave_cell.tasks.view", "leave_cell.tasks.act"],
    "establishment": ["leave_cell.tasks.view", "leave_cell.tasks.act"],
    "substitute": ["leave_cell.tasks.view", "leave_cell.tasks.act"],
}
