from frappe.model.document import Document


class SalesOrderItem(Document):
    def validate(self):
        self.amount = (self.qty or 0) * (self.rate or 0)
