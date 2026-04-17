import frappe
from frappe.model.document import Document

from ...api.ncba_mpesa import generate_ncba_stk_push


class NCBASTKRequest(Document):
	def on_submit(self):
		settings = frappe.get_single("NCBA Paybill Settings")
		generate_ncba_stk_push(self, settings)
