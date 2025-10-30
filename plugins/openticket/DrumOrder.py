import html

def prepare():
    return {
        "name": "OpenTicket – Drum Order",
        "to": "toner@one1.co.il",
        "search_fields": [
            {"key": "id", "label": "ID"},
            {"key": "serial", "label": "Serial"},
            {"key": "ip", "label": "Printer IP"},
        ],
    }

def search_fields_for_group(group):
    if group == "Company_Grouped":
        return [
            {"key": "serial", "label": "Serial"},
            {"key": "ip", "label": "Printer IP"},
        ]
    return [
        {"key": "id", "label": "ID"},
        {"key": "serial", "label": "Serial"},
        {"key": "ip", "label": "Printer IP"},
    ]

def _eq_id(json_value, user_value):
    try:
        return int(json_value) == int(user_value)
    except Exception:
        return str(json_value).strip() == str(user_value).strip()

def _eq_serial(json_value, user_value):
    return str(json_value).strip().upper() == str(user_value).strip().upper()

def _eq_ip(json_value, user_value):
    return str(json_value).strip() == str(user_value).strip()

def search(printers, field_key, value, group="Branches_Grouped"):
    group_list = printers.get(group, []) or []
    out = []
    for e in group_list:
        if field_key == "id" and _eq_id(e.get("ID", ""), value):
            out.append(e)
        elif field_key == "serial" and _eq_serial(e.get("Serial", ""), value):
            out.append(e)
        elif field_key == "ip" and _eq_ip(e.get("Printer IP", ""), value):
            out.append(e)
    return out

def extract(entry, group="Branches_Grouped"):
    if group == "Company_Grouped":
        customer = "סטימצקי"
        address = "מתחם לב הארץ 0, ראש העין שדרות הדלקים"
        contact = "דימה"
        phone = "0542050462"
    else:
        customer = "סטימצקי"
        store = entry.get("storeInfo") or {}
        address = str(store.get("Location","")).strip()
        contact = str(store.get("Manager","")).strip()
        phone = str(store.get("Phone","")).strip()
    return {
        "customer": customer,
        "branch_id": str(entry.get("ID","")).strip(),
        "serial": str(entry.get("Serial","")).strip(),
        "model": str(entry.get("Model") or entry.get("Type") or "").strip(),
        "address": address,
        "contact": contact,
        "phone": phone,
        "items": [],
        "group": group,
    }

def collect(spec, data):
    while True:
        t = input("Drum type: ").strip()
        if t:
            break
        print("Drum type is required.")
    while True:
        q = input("Drum amount: ").strip()
        if q.isdigit() and int(q) > 0:
            qn = int(q)
            break
        print("Please enter a whole number > 0.")
    data["items"] = [{"type": t, "qty": qn}]
    return data

def make_subject(fields):
    base = "הזמנת דרמים"
    parts = [p for p in [fields.get("customer"), fields.get("model")] if p]
    s = f"{base} - " + " | ".join(parts) if parts else base
    bid = str(fields.get("branch_id","")).strip()
    group = fields.get("group","")
    if group != "Company_Grouped" and bid:
        s = f"{s} [{bid}]"
    return s

def make_html(fields, to_addr):
    customer = html.escape(fields.get("customer",""))
    serial   = html.escape(fields.get("serial",""))
    model    = html.escape(fields.get("model",""))
    address  = html.escape(fields.get("address",""))
    contact  = html.escape(fields.get("contact",""))
    phone    = html.escape(fields.get("phone",""))
    items    = fields.get("items", [])
    if items:
        type_str = html.escape(str(items[0]["type"]))
        qty_total = int(items[0]["qty"])
    else:
        type_str = ""
        qty_total = 0
    td_label    = "padding:10px 12px;border:1px solid #ccc;font-weight:600;width:260px;"
    td_value    = "padding:10px 12px;border:1px solid #ccc;"
    th_style    = "padding:12px;border:1px solid #ccc;font-size:18px;text-align:center;font-weight:800;"
    table_style = "border-collapse:collapse;width:100%;max-width:900px;mso-table-lspace:0pt;mso-table-rspace:0pt;"
    wrap        = "white-space:pre-wrap;word-wrap:break-word;"
    title = "הזמנת דרמים"
    return (
        f'<div dir="rtl" style="font-family:Arial, sans-serif;line-height:1.6;font-size:14px;">'
        f'<table style="{table_style}" role="presentation">'
        f'<tr><th colspan="2" style="{th_style}">{title}</th></tr>'
        f'<tr><td style="{td_label}">שם הלקוח</td><td style="{td_value}">{customer}</td></tr>'
        f'<tr><td style="{td_label}">מספר סידורי</td><td style="{td_value}">{serial}</td></tr>'
        f'<tr><td style="{td_label}">דגם המכשיר</td><td style="{td_value}">{model}</td></tr>'
        f'<tr><td style="{td_label}">סוג דרם</td><td style="{td_value}">{type_str}</td></tr>'
        f'<tr><td style="{td_label}">כמות דרמים</td><td style="{td_value}">{qty_total}</td></tr>'
        f'<tr><td style="{td_label}">כתובת מלאה לאספקת המשלוח</td><td style="{td_value}{wrap}">{address}</td></tr>'
        f'<tr><td style="{td_label}">שם איש קשר</td><td style="{td_value}">{contact}</td></tr>'
        f'<tr><td style="{td_label}">מספר טלפון נייד</td><td style="{td_value}">{phone}</td></tr>'
        f'</table></div>'
    )
