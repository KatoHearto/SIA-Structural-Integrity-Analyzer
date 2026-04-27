app_name = "testapp"
app_title = "Test App"

doc_events = {
    "Sales Order": {
        "on_submit": "testapp.testapp.selling.doctype.sales_order.sales_order.on_submit_hook",
        "validate": "testapp.testapp.selling.doctype.sales_order.sales_order.validate_hook",
    },
    "Customer": {
        "after_insert": "testapp.testapp.selling.doctype.customer.customer.after_insert_hook",
    },
}

scheduler_events = {
    "daily": [
        "testapp.testapp.selling.doctype.customer.customer.daily_cleanup",
    ]
}
