# Frappe/Django-style hook registration using string references.
# SIA should resolve these to pyapp.ops symbols and add string_ref edges.

doc_events = {
    "SalesInvoice": {
        "on_submit": "pyapp.ops.fetch_profile",
        "validate": "pyapp.ops.read_cli_payload",
    },
}

scheduler_events = {
    "daily": "pyapp.ops.StateWriter",
}
