// Frappe form script for Sales Order.
// SIA resolves frappe.call method strings to Python symbols via string_ref edges.

frappe.ui.form.on("Sales Order", {
    onload: function(frm) {
        frappe.call({
            method: "testapp.testapp.selling.doctype.sales_order.sales_order.SalesOrder.validate",
            args: { name: frm.doc.name }
        });
    },
    customer: function(frm) {
        frappe.call({
            method: "testapp.testapp.selling.doctype.customer.customer.Customer.on_submit",
            args: { name: frm.doc.customer }
        });
    }
});
