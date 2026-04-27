import frappe
from frappe.model.document import Document


class SalesOrder(Document):
    def validate(self):
        self.total = sum(row.amount for row in self.items)

    def on_submit(self):
        customer_doc = frappe.get_doc("Customer", self.customer)
        customer_name = frappe.db.get_value("Customer", self.customer, "customer_name")
        all_items = frappe.get_all("Sales Order Item", filters={"parent": self.name})
        frappe.db.set_value("Sales Order", self.name, "status", "Submitted")
