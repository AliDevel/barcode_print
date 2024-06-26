# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, scrub
from frappe.utils import flt

from erpnext.accounts.utils import get_fiscal_year


def execute(filters=None):
    return Analytics(filters).run()


class Analytics(object):
    def __init__(self, filters=None):
        self.filters = frappe._dict(filters or {})
        self.date_field = (
            "transaction_date"
            if self.filters.doc_type in ["Sales Order", "Purchase Order"]
            else "posting_date"
        )

    def run(self):
        items_list = []
        if self.filters.supplier:
            if self.filters.item:
                get_supp_data = frappe.db.sql(
                    """select based_on_value from `tabParty Specific Item` 
                    where based_on_value=%s and party_type='Supplier' and party=%s """,
                    (self.filters.item, self.filters.supplier),
                )
            else:
                get_supp_data = frappe.db.sql(
                    """select based_on_value from `tabParty Specific Item` 
                    where restrict_based_on='Item' and party_type='Supplier' and party=%s """,
                    (self.filters.supplier,),
                )
            if get_supp_data:
                for x in get_supp_data:
                    items_list.append(str(x[0]))

        self.get_columns(items_list)
        self.get_data(items_list)

        return self.columns, self.data, None, None

    def get_columns(self, items_list):
        self.columns = [
            {
                "label": _(self.filters.tree_type),
                "options": self.filters.tree_type if self.filters.tree_type != "Order Type" else "",
                "fieldname": "entity",
                "fieldtype": "Link" if self.filters.tree_type != "Order Type" else "Data",
                "width": 140 if self.filters.tree_type != "Order Type" else 200,
            }
        ]
        if self.filters.tree_type in ["Customer", "Supplier", "Item"]:
            self.columns.append(
                {
                    "label": _(self.filters.tree_type + " Name"),
                    "fieldname": "entity_name",
                    "fieldtype": "Data",
                    "width": 140,
                }
            )
            self.columns.append(
                {
                    "label": _("Address"),
                    "fieldname": "address",
                    "fieldtype": "Data",
                    "width": 140,
                }
            )
            self.columns.append(
                {
                    "label": _("Territory"),
                    "fieldname": "territory",
                    "fieldtype": "Data",
                    "width": 140,
                }
            )
            self.columns.append(
                {
                    "label": _("Tax ID"),
                    "fieldname": "tax_id",
                    "fieldtype": "Data",
                    "width": 140,
                }
            )

        for item in items_list:
            item_name = frappe.db.get_value("Item", item, "item_name")
            self.columns.append(
                {
                    "label": _(f"{item} - {item_name} Quantity"),
                    "fieldname": scrub(item),
                    "fieldtype": "Float",
                    "width": 120,
                }
            )

        self.columns.append(
            {"label": _("Total"), "fieldname": "total", "fieldtype": "Float", "width": 120}
        )

    def get_data(self, items_list):
        if self.filters.tree_type in ["Customer", "Supplier"]:
            self.get_sales_transactions_based_on_customers_or_suppliers(items_list)
            self.get_rows(items_list)

    def get_sales_transactions_based_on_customers_or_suppliers(self, items_list):
        if self.filters["value_quantity"] == "Value":
            value_field = "chd.amount as value_field"
        else:
            value_field = "chd.qty as value_field"

        if self.filters.tree_type == "Customer":
            entity = "sal.customer as entity"
            entity_name = "sal.customer_name as entity_name"
            customer_fields = ", cus.address, cus.territory, cus.tax_id"
            join_customer = "left join `tabCustomer` as cus on sal.customer = cus.name"
        else:
            entity = "supplier as entity"
            entity_name = "supplier_name as entity_name"
            customer_fields = ", '' as address, '' as territory, '' as tax_id"
            join_customer = ""

        if len(items_list) > 1:
            self.entries = frappe.db.sql(
                """select {0}, {1}, {2}, {3}, chd.item_code as item_code, it.item_name as item_name {4}
                from `tab{5}` as sal 
                inner join `tabSales Invoice Item` as chd on sal.name=chd.parent 
                inner join `tabItem` as it on chd.item_code=it.name
                {6}
                where sal.docstatus=1 and sal.company='{7}' and {3} between '{8}' and '{9}' and chd.item_code in {10} """.format(
                    entity,
                    entity_name,
                    value_field,
                    self.date_field,
                    customer_fields,
                    self.filters.doc_type,
                    join_customer,
                    self.filters.company,
                    self.filters.from_date,
                    self.filters.to_date,
                    tuple(items_list),
                ),
                as_dict=1,
            )
        else:
            self.entries = frappe.db.sql(
                """select {0}, {1}, {2}, {3}, chd.item_code as item_code, it.item_name as item_name {4}
                from `tab{5}` as sal 
                inner join `tabSales Invoice Item` as chd on sal.name=chd.parent 
                inner join `tabItem` as it on chd.item_code=it.name
                {6}
                where sal.docstatus=1 and sal.company='{7}' and {3} between '{8}' and '{9}' and chd.item_code = {10} """.format(
                    entity,
                    entity_name,
                    value_field,
                    self.date_field,
                    customer_fields,
                    self.filters.doc_type,
                    join_customer,
                    self.filters.company,
                    self.filters.from_date,
                    self.filters.to_date,
                    items_list[0],
                ),
                as_dict=1,
            )

        self.entity_names = {}
        self.customer_details = {}
        for d in self.entries:
            self.entity_names.setdefault(d.entity, d.entity_name)
            self.customer_details[d.entity] = {
                "address": d.address,
                "territory": d.territory,
                "tax_id": d.tax_id,
            }

    def get_sales_transactions_based_on_items(self):
        if self.filters["value_quantity"] == "Value":
            value_field = "base_net_amount"
        else:
            value_field = "stock_qty"

        self.entries = frappe.db.sql(
            """
            select i.item_code as entity, i.item_name as entity_name, i.stock_uom, 
            i.{value_field} as value_field, s.{date_field}
            from `tab{doctype} Item` i , `tab{doctype}` s
            where s.name = i.parent and i.docstatus = 1 and s.company = %s
            and s.{date_field} between %s and %s
            """.format(
                date_field=self.date_field,
                value_field=value_field,
                doctype=self.filters.doc_type,
            ),
            (self.filters.company, self.filters.from_date, self.filters.to_date),
            as_dict=1,
        )

        self.entity_names = {}
        for d in self.entries:
            self.entity_names.setdefault(d.entity, d.entity_name)

    def get_rows(self, items_list):
        self.data = []
        self.get_periodic_data(items_list)

        for entity, item_data in self.entity_item_data.items():
            row = {
                "entity": entity,
                "entity_name": self.entity_names.get(entity) if hasattr(self, "entity_names") else None,
                "address": self.customer_details.get(entity, {}).get("address", ""),
                "territory": self.customer_details.get(entity, {}).get("territory", ""),
                "tax_id": self.customer_details.get(entity, {}).get("tax_id", ""),
            }
            total = 0
            for item in items_list:
                amount = flt(item_data.get(item, 0.0))
                row[scrub(item)] = amount
                total += amount

            row["total"] = total

            self.data.append(row)

    def get_periodic_data(self, items_list):
        self.entity_item_data = frappe._dict()
        for item in items_list:
            for d in self.entries:
                if d.item_code == item:
                    self.entity_item_data.setdefault(d.entity, frappe._dict()).setdefault(item, 0.0)
                    self.entity_item_data[d.entity][item] += flt(d.value_field)
