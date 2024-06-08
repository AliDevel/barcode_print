# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _, scrub
from frappe.utils import add_days, add_to_date, flt, getdate

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
		from datetime import datetime, timedelta
		start_date = datetime.strptime(self.filters.from_date, "%Y-%m-%d")
		end_date = datetime.strptime(self.filters.to_date, "%Y-%m-%d")
		date_list = []
		
		current_date = start_date
		while current_date <= end_date:
			date_list.append(str(current_date).split(" ")[0])
			current_date += timedelta(days=1)
		if self.filters.supplier:
			if self.filters.item:
				get_supp_data = frappe.db.sql("""select based_on_value from `tabParty Specific Item` where based_on_value=%s and party_type='Supplier' and party=%s """,(self.filters.item,self.filters.supplier))
			else:
				get_supp_data = frappe.db.sql("""select based_on_value from `tabParty Specific Item` where restrict_based_on='Item' and party_type='Supplier' and party=%s """,(self.filters.supplier))
			if get_supp_data:
				for x in get_supp_data:
					items_list.append(str(x[0]))
		self.get_columns(items_list, date_list)
		self.get_data(items_list, date_list)


		return self.columns, self.data, None, None

	def get_columns(self, items_list, date_list):
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

		for items in date_list:
			self.columns.append(
				{"label": _(items), "fieldname": scrub(items), "fieldtype": "Float", "width": 120}
			)

		self.columns.append(
			{"label": _("Total"), "fieldname": "total", "fieldtype": "Float", "width": 120}
		)

	def get_data(self, items_list, date_list):
		if self.filters.tree_type in ["Customer", "Supplier"]:
			self.get_sales_transactions_based_on_customers_or_suppliers(items_list, date_list)
			self.get_rows(items_list, date_list)

	def get_sales_transactions_based_on_customers_or_suppliers(self, items_list, date_list):
		if self.filters["value_quantity"] == "Value":
			value_field = "chd.amount as value_field"
		else:
			value_field = "chd.qty as value_field"

		if self.filters.tree_type == "Customer":
			entity = "sal.customer as entity"
			entity_name = "sal.customer_name as entity_name"
		else:
			entity = "supplier as entity"
			entity_name = "supplier_name as entity_name"
		
		if len(items_list) > 1:
			self.entries = frappe.db.sql("""select {0}, {1}, {2}, {3}, chd.item_code as item_code from `tab{4}` as sal inner join `tabSales Invoice Item` as chd on sal.name=chd.parent  where sal.docstatus=1 and sal.company='{5}' and {3} between '{6}' and '{7}' and chd.item_code in {8} """.format(entity, entity_name, value_field, self.date_field, self.filters.doc_type, self.filters.company,self.filters.from_date, self.filters.to_date, tuple(items_list)), as_dict=1)
		else:
			self.entries = frappe.db.sql("""select {0}, {1}, {2}, {3}, chd.item_code as item_code from `tab{4}` as sal inner join `tabSales Invoice Item` as chd on sal.name=chd.parent  where sal.docstatus=1 and sal.company='{5}' and {3} between '{6}' and '{7}' and chd.item_code = {8} """.format(entity, entity_name, value_field, self.date_field, self.filters.doc_type, self.filters.company,self.filters.from_date, self.filters.to_date, items_list[0]), as_dict=1)
			
		self.entity_names = {}
		for d in self.entries:
			self.entity_names.setdefault(d.entity, d.entity_name)

	def get_sales_transactions_based_on_items(self):

		if self.filters["value_quantity"] == "Value":
			value_field = "base_net_amount"
		else:
			value_field = "stock_qty"

		self.entries = frappe.db.sql(
			"""
			select i.item_code as entity, i.item_name as entity_name, i.stock_uom, i.{value_field} as value_field, s.{date_field}
			from `tab{doctype} Item` i , `tab{doctype}` s
			where s.name = i.parent and i.docstatus = 1 and s.company = %s
			and s.{date_field} between %s and %s
		""".format(
				date_field=self.date_field, value_field=value_field, doctype=self.filters.doc_type
			),
			(self.filters.company, self.filters.from_date, self.filters.to_date),
			as_dict=1,
		)

		self.entity_names = {}
		for d in self.entries:
			self.entity_names.setdefault(d.entity, d.entity_name)

	def get_rows(self, items_list, date_list):
		self.data = []
		self.get_periodic_data(items_list, date_list)

		for entity, period_data in self.entity_periodic_data.items():
			row = {
				"entity": entity,
				"entity_name": self.entity_names.get(entity) if hasattr(self, "entity_names") else None,
			}
			total = 0
			for period in date_list:
				amount = flt(period_data.get(period, 0.0))
				row[scrub(period)] = amount
				total += amount

			row["total"] = total

			self.data.append(row)

	def get_periodic_data(self, items_list, date_list):
		self.entity_periodic_data = frappe._dict()
		for period in date_list:
			for d in self.entries:
				from datetime import datetime as dt
				a = dt.strptime(str(period), "%Y-%m-%d")
				b = dt.strptime(str(d.posting_date), "%Y-%m-%d")
				if a == b:
					self.entity_periodic_data.setdefault(d.entity, frappe._dict()).setdefault(period, 0.0)
					self.entity_periodic_data[d.entity][period] += flt(d.value_field)
