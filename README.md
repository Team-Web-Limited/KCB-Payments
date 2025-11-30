### KCB Payments

KCB Payments is a custom [frappe](https://frappe.io/framework) application that integrates with [KCB's BUNI API](https://buni.kcbgroup.com/). It is built to extend [ERPNext](https://frappe.io/erpnext/ke), enabling seamless mobile payments from customers bo businesses via Mpesa's _Mpesa Express API Service_

### Requirements

1. [ERPNext](https://github.com/frappe/erpnext)
2. [Payments](https://github.com/frappe/payments)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app kcb_payments
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/kcb_payments
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
