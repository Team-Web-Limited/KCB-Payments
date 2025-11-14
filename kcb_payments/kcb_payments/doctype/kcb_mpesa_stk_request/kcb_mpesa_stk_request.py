# Copyright (c) 2025, Team Web Africa and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from ...api.kcb_mpesa import generate_stk_push
from ...utils.utils import get_stk_push_callback


class KCBMpesaSTKRequest(Document):
	def on_submit(self):
		self.till_no = frappe.db.get_value("KCB Mpesa Settings", self.payment_gateway[10:], "till_no")

		args = {
			"phone_number": self.phone_number,
			"request_amount": self.amount,
			"invoice_number": f"{self.till_no}-{self.reference_name}",
			"callback_url": get_stk_push_callback(),
			# callback_url": "https://posthere.io/f613-4b7f-b82b",
			"transaction_description": self.transaction_desc,
			"payment_gateway": str(self.payment_gateway),
			"settings": str(self.payment_gateway[10:]),
			"kcb_mpesa_stk_request": str(self.name),
		}

		try:
			generate_stk_push(**args)
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), "KCB STK Push on Submit Error")
			frappe.throw(f"Failed to initiate KCB STK Push: {e!s}")
