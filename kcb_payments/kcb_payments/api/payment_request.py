import frappe


@frappe.whitelist()
def get_payment_gateway_from_mop(mode_of_payment: str, company: str) -> str:
	payment_gateway = None
	try:
		if not frappe.db.exists("Mode of Payment", mode_of_payment):
			return None
		mop_doc = frappe.get_doc("Mode of Payment", mode_of_payment)
		account_entry = next((acc for acc in mop_doc.accounts if acc.company == company), None)
		if account_entry:
			payment_account = account_entry.default_account
			if frappe.db.exists("Payment Gateway Account", {"payment_account": payment_account}):
				try:
					pg_account = frappe.get_doc(
						"Payment Gateway Account", {"payment_account": payment_account}
					)
					if pg_account and pg_account.payment_gateway:
						payment_gateway = pg_account.payment_gateway
				except Exception:
					pass
			else:
				default_pg_account = frappe.get_value(
					"Payment Gateway Account", {"is_default": 1}, "payment_gateway"
				)
				if default_pg_account:
					payment_gateway = default_pg_account
	except Exception:
		pass

	return payment_gateway


@frappe.whitelist()
def get_mop_from_payment_gateway(payment_gateway: str, company: str) -> str:
	"""Get mode of payment associated with the given payment gateway"""
	mode_of_payment = None
	try:
		if not payment_gateway or not frappe.db.exists("Payment Gateway", payment_gateway):
			return None

		pg_accounts = frappe.get_all(
			"Payment Gateway Account",
			filters={"payment_gateway": payment_gateway},
			fields=["payment_account"],
		)

		if not pg_accounts:
			return None

		for pg_account in pg_accounts:
			payment_account = pg_account.payment_account

			mop_accounts = frappe.get_all(
				"Mode of Payment Account",
				filters={"default_account": payment_account, "company": company},
				fields=["parent"],
			)

			if mop_accounts:
				mode_of_payment = mop_accounts[0].parent
				break

	except Exception:
		frappe.log_error(frappe.get_traceback(), "get_mop_from_payment_gateway Error")
		pass

	return mode_of_payment
