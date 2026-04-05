# Copyright (c) 2024, Navari Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document


class KCBPaymentsReconciliation(Document):

	_table_fieldnames = []

	def save(self):
		return
	
	def db_insert(self, *args, **kwargs):
		pass

	def load_from_db(self):
		pass

	def db_update(self):
		pass

	def delete(self):
		pass

	@staticmethod
	def get_list(args):
		pass

	@staticmethod
	def get_count(args):
		pass

	@staticmethod
	def get_stats(args):
		pass

	@frappe.whitelist()
	def allocate_entries(self, args):
		"""Allocate payments to invoices"""
		self.validate_entries()

		entries = []
		for pay in args.get("payments", []):
			pay.update({"unreconciled_amount": pay.get("amount")})
			for inv in args.get("invoices", []):
				if pay.get("amount") >= inv.get("outstanding_amount"):
					res = self.get_allocated_entry(pay, inv, inv["outstanding_amount"])
					pay["amount"] = flt(pay.get("amount")) - flt(inv.get("outstanding_amount"))
					inv["outstanding_amount"] = 0
				else:
					res = self.get_allocated_entry(pay, inv, pay["amount"])
					inv["outstanding_amount"] = flt(inv.get("outstanding_amount")) - flt(pay.get("amount"))
					pay["amount"] = 0

				entries.append(res)

				if pay.get("amount") == 0:
					break
				elif inv.get("outstanding_amount") == 0:
					continue
			else:
				break

		self.set("allocation", [])
		for entry in entries:
			if entry["allocated_amount"] != 0:
				row = self.append("allocation", {})
				row.update(entry)

	def get_allocated_entry(self, pay, inv, allocated_amount):
		"""Get allocation entry dictionary"""
		return frappe._dict({
			"payment_id": pay.get("payment_id"),
			"payment_doctype": pay.get("payment_doctype", "KCB Payment Transaction"),
			"source": pay.get("source", "KCB"),
			"invoice": inv.get("invoice"),
			"unreconciled_amount": pay.get("unreconciled_amount"),
			"amount": pay.get("amount"),
			"allocated_amount": allocated_amount,
		})

	def validate_entries(self):
		"""Validate that entries exist"""
		if not self.get("invoices"):
			frappe.throw("No invoices found")
		if not self.get("mpesa_payments"):
			frappe.throw("No payments found")

	def check_if_latest(self):
		"""Skip the modified check for this custom doctype"""
		return

