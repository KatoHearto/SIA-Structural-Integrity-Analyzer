import frappe
from frappe.model.document import Document


class Customer(Document):
    def validate(self):
        if not self.customer_name:
            frappe.throw("Customer Name is required")

    def on_submit(self):
        frappe.db.set_value("Customer", self.name, "status", "Active")
